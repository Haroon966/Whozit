# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import cv2
import numpy as np

from whozit.face_utils import face_alignment
from whozit.log import Logger
from whozit.onnx_utils import create_onnx_session

__all__ = ['BaseRecognizer', 'PreprocessConfig']


@dataclass
class PreprocessConfig:
    input_mean: float | list[float] = 127.5
    input_std: float | list[float] = 127.5
    input_size: tuple[int, int] = (112, 112)


class BaseRecognizer(ABC):
    @abstractmethod
    def __init__(
        self,
        *,
        model_path: str,
        preprocessing: PreprocessConfig,
        providers: list[str] | None = None,
    ) -> None:
        self.input_mean = preprocessing.input_mean
        self.input_std = preprocessing.input_std
        self.input_size = preprocessing.input_size
        self.model_path = model_path
        self.providers = providers
        self._initialize_model()

    def _initialize_model(self) -> None:
        try:
            self.session = create_onnx_session(self.model_path, providers=self.providers)
            input_cfg = self.session.get_inputs()[0]
            self.input_name = input_cfg.name
            input_shape = input_cfg.shape
            model_input_size = tuple(input_shape[2:4][::-1])
            if model_input_size != self.input_size:
                Logger.warning(f'Model input size {model_input_size} differs from configured size {self.input_size}')
            self.output_names = [output.name for output in self.session.get_outputs()]
            if len(self.output_names) != 1:
                raise ValueError(f'Expected exactly one output node, got {len(self.output_names)}: {self.output_names}')
            Logger.info(f'Successfully initialized face encoder from {self.model_path}')
        except Exception as e:
            Logger.error(f"Failed to load face encoder model from '{self.model_path}'", exc_info=True)
            raise RuntimeError(f"Failed to initialize model session for '{self.model_path}'") from e

    def preprocess(self, face_img: np.ndarray) -> np.ndarray:
        resized_img = cv2.resize(face_img, self.input_size)

        if isinstance(self.input_std, list | tuple):
            rgb_img = cv2.cvtColor(resized_img, cv2.COLOR_BGR2RGB).astype(np.float32)
            normalized_img = (rgb_img - np.array(self.input_mean, dtype=np.float32)) / np.array(
                self.input_std, dtype=np.float32
            )
            blob = np.transpose(normalized_img, (2, 0, 1))
            blob = np.expand_dims(blob, axis=0)
        else:
            blob = cv2.dnn.blobFromImage(
                resized_img,
                scalefactor=1.0 / self.input_std,
                size=self.input_size,
                mean=(self.input_mean, self.input_mean, self.input_mean),
                swapRB=True,
            )
        return blob

    def get_embedding(self, image: np.ndarray, landmarks: np.ndarray | None = None) -> np.ndarray:
        if landmarks is not None:
            aligned_face, _ = face_alignment(image, landmarks, image_size=self.input_size)
        else:
            aligned_face = image
        face_blob = self.preprocess(aligned_face)
        return self.session.run(self.output_names, {self.input_name: face_blob})[0]

    def get_normalized_embedding(self, image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        embedding = self.get_embedding(image, landmarks).ravel()
        norm = np.linalg.norm(embedding)
        return embedding / norm if norm > 0 else embedding

    def __call__(self, image: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        return self.get_normalized_embedding(image, landmarks)
