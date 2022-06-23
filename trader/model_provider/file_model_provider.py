import logging
import checksumdir
import numpy as np
import tensorflow as tf

from .abstract_model_provider import AbstractModelProvider


logger = logging.getLogger(__name__)


class FileModelProvider(AbstractModelProvider):

    def __init__(self, path):
        self.path = path
        self.model_hash = None
        self.model = None
        self._check_model()
        logger.warning("Model initialized from {0}".format(self.path))

    def predict(self, observation):
        self._check_model()
        obs_transformed = self._prepare_observation(observation)
        action_probs = self.model(obs_transformed)
        action = np.argmax(action_probs)
        logger.debug("Action probabilities: {0} | Predicted action: {1}".format(action_probs, action))
        return action

    def _check_model(self):
        model_hash = checksumdir.dirhash(self.path)
        if model_hash != self.model_hash:
            self.model = tf.keras.models.load_model(self.path)
            self.model.compile()
            self.model_hash = model_hash

