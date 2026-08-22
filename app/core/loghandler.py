"""
Custom log handler with color-coded console output and plain file output.

To add other handlers (like file handlers) later, just use:

file_handler = logging.FileHandler('app.log')
file_handler.setFormatter(plain_formatter)
root_logger.addHandler(file_handler)
"""
import logging

class ColorFormatter(logging.Formatter):

    LIGHTGREY = "\x1b[37;21m"
    DARK_GRAY = "\033[1;30m"
    YELLOW = "\x1b[33;20m"
    WHITE = "\x1b[37;20m"
    RED = "\x1b[31;20m"
    GREEN = "\x1b[32;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"
    TEMPLATE = "{c1}%(asctime)s " + RESET  + \
               "{c3}%(levelname)9s > " + RESET + \
               "{c4}%(message)s" + RESET + " " + \
               "{c5}(%(filename)s:%(lineno)d)" + RESET

    FORMATS = {
        logging.DEBUG: TEMPLATE.format(c1=DARK_GRAY, c3=DARK_GRAY, c4=DARK_GRAY, c5=DARK_GRAY),
        logging.INFO: TEMPLATE.format(c1=WHITE, c3=GREEN, c4=WHITE, c5=DARK_GRAY),
        logging.WARNING: TEMPLATE.format(c1=WHITE, c3=YELLOW, c4=WHITE, c5=DARK_GRAY),
        logging.ERROR: TEMPLATE.format(c1=WHITE, c3=RED, c4=WHITE, c5=DARK_GRAY),
        logging.CRITICAL: TEMPLATE.format(c1=WHITE, c3=BOLD_RED, c4=WHITE, c5=DARK_GRAY),
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno) 
        formatter = logging.Formatter(log_fmt, datefmt="%y.%m.%d %H:%M:%S")
        message = formatter.format(record)
        return message 


# Plain formatter without color codes (for file handlers, etc.)
plain_formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)9s > %(message)s (%(filename)s:%(lineno)d)",
    datefmt="%y.%m.%d %H:%M:%S" 
)

# Get the root logger and remove any existing handlers
root_logger = logging.getLogger()

# Remove any existing handlers to prevent duplicate logging
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# Create console handler with ColorFormatter (only StreamHandler gets colors)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(ColorFormatter())

# Add the stream handler to root logger so all loggers inherit it
root_logger.addHandler(stream_handler)

# Configure formatter for any other handlers (they will use plain_formatter)
# When adding file handlers or other handlers, use: handler.setFormatter(plain_formatter)
logger = logging.getLogger(__name__)

# Set the root logger's level globally so all loggers inherit the correct level
root_logger.setLevel(logging.INFO)


if __name__ == "__main__":
    logger.setLevel(logging.DEBUG) 
    logger.debug("This is a debug message.")
    logger.info("This is an info message.")
    logger.warning("This is a warning message.")
    logger.error("This is an error message.")
    logger.critical("This is a critical message.")
