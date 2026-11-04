"""Lich dang: a calendar of WordPress posts inside Open WebUI. Posts wait here and go out at their time through the
WordPress REST API with an application password; the schedule is mirrored into the Open WebUI calendar.

router: mounted at /api/v1/cqf/lich by cqf_openwebui.router. start(): the background sender, once per process.
"""


def start():
    from . import worker

    return worker.start()
