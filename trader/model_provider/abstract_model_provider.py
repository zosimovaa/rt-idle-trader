import tensorflow as tf
from abc import ABC, abstractmethod


class ModelProviderError(Exception):
    pass


class AbstractModelProvider(ABC):

    @abstractmethod
    def predict(self, observation):
        pass

    @staticmethod
    def _prepare_observation(observation):
        # todo сделать возможность трансформаци для моделей с одним входом
        obs_transformed = [tf.expand_dims(tf.convert_to_tensor(obs), 0) for obs in observation]
        return obs_transformed
