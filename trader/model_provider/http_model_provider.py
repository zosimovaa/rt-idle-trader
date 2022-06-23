import json
import pickle
import logging
import requests
from .abstract_model_provider import ModelProviderError
from .abstract_model_provider import AbstractModelProvider


logger = logging.getLogger(__name__)


class HttpModelProvider(AbstractModelProvider):
    def __init__(self, host, path):
        self.host = host
        self.path = path
        self.url = host + path
        logger.warning("Initialized with url: {0}".format(self.url))

    def predict(self, observation):
        obs_transformed = self._prepare_observation(observation)

        data_bin = pickle.dumps(obs_transformed)
        response = requests.post(self.url, data=data_bin)
        response = json.loads(response.content)
        logger.debug("Response: {}".format(str(response)))

        if not isinstance(response, dict):
            raise ModelProviderError("Bad response {0}".format(response))

        if not response.get("success", False):
            message = response.get("error", "no description")
            logger.error("Response error. Message: {0}".format(message))
            raise ModelProviderError(message)

        else:
            action = response["action"]
            logger.debug("Request completed. Action: {0}".format(action))
        return action
