# Webhooks for external integrations.
from typing import Text

from django.http import HttpRequest, HttpResponse

from zerver.decorator import api_key_only_webhook_view
from zerver.lib.actions import check_send_stream_message
from zerver.lib.response import json_success
from zerver.lib.request import REQ, has_request_variables
from zerver.models import UserProfile


@api_key_only_webhook_view("Heroku")
@has_request_variables
def api_heroku_webhook(request, user_profile, stream=REQ(default="heroku"),
                       head=REQ(), app=REQ(), user=REQ(), url=REQ(), git_log=REQ()):
    # type: (HttpRequest, UserProfile, Text, Text, Text, Text, Text, Text) -> HttpResponse
    template = "{} deployed version {} of [{}]({})\n> {}"
    content = template.format(user, head, app, url, git_log)

    check_send_stream_message(user_profile, request.client, stream, app, content)
    return json_success()
