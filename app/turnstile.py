"""
Cloudflare Turnstile

A minimal Flask extension for Cloudflare Turnstile, mirroring the interface
of Flask-hCaptcha (get_code/verify/init_app + template globals) so the rest
of the app can treat it as a drop-in replacement.
"""

import requests
from flask import request
from markupsafe import Markup

DEFAULTS_IS_ENABLED = True


class Turnstile(object):

    VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

    def __init__(self, app=None):
        self.site_key = None
        self.secret_key = None
        self.is_enabled = False
        self.custom_data = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app, **kwargs):
        self.site_key = app.config.get("TURNSTILE_SITE_KEY")
        self.secret_key = app.config.get("TURNSTILE_SECRET_KEY")
        self.is_enabled = app.config.get("TURNSTILE_ENABLED", DEFAULTS_IS_ENABLED)
        self.custom_data = " ".join(f'data-{key}="{value}"' for key, value in kwargs.items())

        @app.template_global()
        def turnstile_with(**kwargs):
            return Markup(self.get_code(**kwargs))

        @app.context_processor
        def get_code():
            return dict(turnstile=Markup(self.get_code()))

    def get_code(self, **kwargs):
        """
        Returns the Turnstile widget markup (script tag + widget div).
        """
        if not self.is_enabled:
            return ""
        custom_data = " ".join(f'data-{key}="{value}"' for key, value in kwargs.items()) if kwargs else self.custom_data
        return """
        <script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
        <div class="cf-turnstile" data-sitekey="{SITE_KEY}" {DATA}></div>
        """.format(SITE_KEY=self.site_key, DATA=custom_data or "")

    def verify(self, response=None, remote_ip=None):
        if not self.is_enabled:
            return True
        data = {
            "secret": self.secret_key,
            "response": response or request.form.get('cf-turnstile-response'),
            "remoteip": remote_ip or request.environ.get('REMOTE_ADDR'),
        }
        r = requests.post(self.VERIFY_URL, data=data)
        return r.json().get("success", False) if r.status_code == 200 else False
