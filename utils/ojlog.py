import logging
import os

logger = logging.getLogger(__name__)
handler = logging.FileHandler('/home/oj/qduoj/log/backend.log')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

