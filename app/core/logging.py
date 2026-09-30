import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# Never log secrets: password / token / keys / Authorization must not appear
# in log calls anywhere in the codebase (see §42).
