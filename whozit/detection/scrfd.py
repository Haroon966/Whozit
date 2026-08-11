# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
# SCRFD: Sample and Computation Redistribution for Efficient Face Detection
# Paper: https://arxiv.org/abs/2105.04714
from __future__ import annotations

from typing import Literal

import numpy as np

from whozit.common import distance2bbox, distance2kps, non_max_suppression, resize_image
from whozit.constants import SCRFDWeights
from whozit.log import Logger
from whozit.model_store import verify_model_weights
from whozit.onnx_utils import create_onnx_session
from whozit.types import Face

from .base import BaseDetector

__all__ = ['SCRFD']


class SCRFD(BaseDetector):
    supports_landmarks = True
    supports_alignment = True

    def __init__(
        self,
        *,
        model_name: SCRFDWeights = SCRFDWeights.SCRFD_10G_KPS,
        confidence_threshold: float = 0.5,
        nms_threshold: float = 0.4,
        input_size: tuple[int, int] = (640, 640),
        providers: list[str] | None = None,
    ) -> None:
        super().__init__(
            model_name=model_name,
            confidence_threshold=confidence_threshold,
            nms_threshold=nms_threshold,
            input_size=input_size,
            providers=providers,
        )

        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.input_size = input_size
        self.providers = providers

        self._num_feature_maps = 3
        self._feat_stride_fpn = [8, 16, 32]
        self._num_anchors = 2
        self._center_cache: dict = {}

        Logger.info(
            f'Initializing SCRFD with model={self.model_name}, confidence_threshold={self.confidence_threshold}, '
            f'nms_threshold={self.nms_threshold}, input_size={self.input_size}'
        )

        self._model_path = verify_model_weights(self.model_name)
        Logger.info(f'Verified model weights located at: {self._model_path}')

        self._initialize_model(self._model_path)

    def _initialize_model(self, model_path: str) -> None:
        try:
            self.session = create_onnx_session(model_path, providers=self.providers)
            self.input_names = self.session.get_inputs()[0].name
            self.output_names = [x.name for x in self.session.get_outputs()]
            Logger.info(f'Successfully initialized the model from {model_path}')
        except Exception as e:
            Logger.error(f"Failed to load model from '{model_path}': {e}", exc_info=True)
            raise RuntimeError(f"Failed to initialize model session for '{model_path}'") from e

    def preprocess(self, image: np.ndarray) -> np.ndarray:
        image = image.astype(np.float32)
        image = (image - 127.5) / 127.5
        image = image.transpose(2, 0, 1)
        image = np.expand_dims(image, axis=0)
        return image

    def inference(self, input_tensor: np.ndarray) -> list[np.ndarray]:
        return self.session.run(self.output_names, {self.input_names: input_tensor})

    def postprocess(
        self,
        outputs: list[np.ndarray],
        image_size: tuple[int, int],
    ) -> tuple[list[np.ndarray], list[np.ndarray], list[np.ndarray]]:
        scores_list: list[np.ndarray] = []
        bboxes_list = []
        kpss_list = []

        num_feature_maps = self._num_feature_maps
        for idx, stride in enumerate(self._feat_stride_fpn):
            scores = outputs[idx]
            bbox_preds = outputs[num_feature_maps + idx] * stride
            kps_preds = outputs[2 * num_feature_maps + idx] * stride

            fm_height = image_size[0] // stride
            fm_width = image_size[1] // stride
            cache_key = (fm_height, fm_width, stride)

            if cache_key in self._center_cache:
                anchor_centers = self._center_cache[cache_key]
            else:
                y, x = np.mgrid[:fm_height, :fm_width]
                anchor_centers = np.stack((x, y), axis=-1).astype(np.float32)
                anchor_centers = (anchor_centers * stride).reshape(-1, 2)

                if self._num_anchors > 1:
                    anchor_centers = np.tile(anchor_centers[:, None, :], (1, self._num_anchors, 1)).reshape(-1, 2)

                if len(self._center_cache) < 100:
                    self._center_cache[cache_key] = anchor_centers

            pos_indices = np.where(scores >= self.confidence_threshold)[0]
            if len(pos_indices) == 0:
                continue

            bboxes = distance2bbox(anchor_centers, bbox_preds)[pos_indices]
            scores_selected = scores[pos_indices]
            scores_list.append(scores_selected)
            bboxes_list.append(bboxes)

            landmarks = distance2kps(anchor_centers, kps_preds)
            landmarks = landmarks.reshape((landmarks.shape[0], -1, 2))
            kpss_list.append(landmarks[pos_indices])

        return scores_list, bboxes_list, kpss_list

    def detect(
        self,
        image: np.ndarray,
        *,
        max_num: int = 0,
        metric: Literal['default', 'max'] = 'max',
        center_weight: float = 2.0,
    ) -> list[Face]:
        original_height, original_width = image.shape[:2]

        image, resize_factor = resize_image(image, target_shape=self.input_size)
        image_tensor = self.preprocess(image)
        outputs = self.inference(image_tensor)

        scores_list, bboxes_list, kpss_list = self.postprocess(outputs, image_size=image.shape[:2])

        if not scores_list:
            return []

        scores = np.vstack(scores_list)
        scores_ravel = scores.ravel()
        order = scores_ravel.argsort()[::-1]

        bboxes = np.vstack(bboxes_list) / resize_factor
        landmarks = np.vstack(kpss_list) / resize_factor

        pre_det = np.hstack((bboxes, scores)).astype(np.float32, copy=False)
        pre_det = pre_det[order, :]

        keep = non_max_suppression(pre_det, threshold=self.nms_threshold)

        detections = pre_det[keep, :]
        landmarks = landmarks[order, :, :]
        landmarks = landmarks[keep, :, :].astype(np.float32)

        detections, landmarks = self._select_top_detections(
            detections, landmarks, max_num, (original_height, original_width), metric, center_weight
        )

        return self._detections_to_faces(detections, landmarks)
