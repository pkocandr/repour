import asyncio
import logging
import os

from repour import asutil

SHARED_PATH_PREFOLDER = os.environ.get("SHARED_FOLDER", '/tmp')
CALLBACK_LOGS_PATH = os.path.join(SHARED_PATH_PREFOLDER, "repour-logs-callback")

def get_callback_log_path(callback_id):
    return os.path.join(CALLBACK_LOGS_PATH, callback_id + '.log')


class FileCallbackHandler(logging.StreamHandler):
    """
    Handler that logs into {directory}/{callback_id}.log
    """
    def __init__(self, directory=CALLBACK_LOGS_PATH, mode='a', encoding=None, delay=None):
        if os.path.exists(directory):
            if not os.path.isdir(directory):
                raise Exception(directory + " is not a directory! Can't log there")
        else:
            os.makedirs(directory)

        self.filename = directory
        self.mode = mode
        self.encoding = encoding
        self.delay = delay
        logging.Handler.__init__(self)

    def emit(self, record):
        try:
            task = asyncio.Task.current_task()

            if task is not None:
                callback_id = getattr(task, "callback_id", None)
                if callback_id is not None:
                    self.stream = self._open_callback_file(callback_id)
                    logging.StreamHandler.emit(self, record)

                    # need to flush to make sure every reader sees the change
                    self.stream.close()
        except:
            self.handleError(record)

    def _open_callback_file(self, callback_id):
        path = get_callback_log_path(callback_id)
        return open(path, self.mode, encoding=self.encoding)


async def setup_clean_old_logfiles():
    """
    We cleanup old log files that haven't been written to for the past 2 days
    """
    while True:
        for filename in os.listdir(CALLBACK_LOGS_PATH):
            path = os.path.join(CALLBACK_LOGS_PATH, filename)

            epoch_filename = int(os.stat(path).st_ctime)
            current_epoch = calendar.timegm(time.gmtime())

            # 172800 seconds = 2 days
            if current_epoch - epoch_filename > 172800:
                logger.info("Removing old logfile: " + path)
                asutil.safe_remove_file(path)

        # Run every hour
        await asyncio.sleep(3600)