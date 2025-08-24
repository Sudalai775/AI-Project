import logging
import os

def setup_logging():
	logging.basicConfig(
		filename='assistant.log',
		level=logging.INFO,
		format='%(asctime)s - %(levelname)s - %(message)s'
	)
	logger = logging.getLogger()
	return logger
