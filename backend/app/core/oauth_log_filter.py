"""Uvicorn formats its access record after request handling; strip OAuth queries."""
import logging


class OAuthAccessFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str) and any(path in args[2] for path in (
                    '/providers/X_API/oauth/', '/providers/INSTAGRAM_API/oauth/')):
                args[2] = args[2].split('?', 1)[0]
                record.args = tuple(args)
        return True


def install_oauth_access_filter():
    logger = logging.getLogger('uvicorn.access')
    if not any(isinstance(f, OAuthAccessFilter) for f in logger.filters):
        logger.addFilter(OAuthAccessFilter())
