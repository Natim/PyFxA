# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from six import string_types
from six.moves.urllib.parse import urlparse, urlunparse, urlencode, parse_qs

from fxa.errors import OutOfProtocolError, ScopeMismatchError
from fxa._utils import APIClient, scope_matches


DEFAULT_SERVER_URL = "https://oauth.accounts.firefox.com"


class Client(object):
    """Client for talking to the Firefox Accounts OAuth server"""

    def __init__(self, client_id=None, client_secret=None, server_url=None):
        self.client_id = client_id
        self.client_secret = client_secret
        if server_url is None:
            server_url = DEFAULT_SERVER_URL
        if isinstance(server_url, string_types):
            self.apiclient = APIClient(server_url)
        else:
            self.apiclient = server_url

    @property
    def server_url(self):
        return self.apiclient.server_url

    def get_redirect_url(self, state="", redirect_uri=None, scope=None,
                         action=None, email=None, client_id=None):
        """Get the URL to redirect to to initiate the oauth flow."""
        if client_id is None:
            client_id = self.client_id
        params = {
            "client_id": client_id,
            "state": state,
        }
        if redirect_uri is not None:
            params["redirect_uri"] = redirect_uri
        if scope is not None:
            params["scope"] = scope
        if action is not None:
            params["action"] = action
        if email is not None:
            params["email"] = email
        query_str = urlencode(params)
        authorization_url = urlparse(self.server_url + "/v1/authorization")
        return urlunparse(authorization_url._replace(query=query_str))

    def trade_code(self, code, client_id=None, client_secret=None):
        """Trade the authentication code for a longer lived token.

        :param code: the authentication code from the oauth redirect dance.
        :param client_id: the string generated during FxA client registration.
        :param client_secret: the related secret string.
        :returns: a dict with user id and authorized scopes for this token.
        """
        if client_id is None:
            client_id = self.client_id
        if client_secret is None:
            client_secret = self.client_secret
        url = '/v1/token'
        body = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret
        }
        resp = self.apiclient.post(url, body)

        if 'access_token' not in resp:
            error_msg = 'access_token missing in OAuth response'
            raise OutOfProtocolError(error_msg)

        return resp['access_token']

    def authorize_code(self, assertion, scope=None, client_id=None):
        """Trade an identity assertion for an oauth authorization code.

        This method takes an identity assertion for a user and uses it to
        generate an oauth authentication code.  This code can in turn be
        traded for a full-blown oauth token.

        Note that the authorize_token() method does the same thing but skips
        the intermediate step of using a short-lived code, and hence this
        method is likely only useful for testing purposes.

        :param assertion: an identity assertion for the target user.
        :param scope: optional scope to be provided by the token.
        :param client_id: the string generated during FxA client registration.
        """
        if client_id is None:
            client_id = self.client_id
        url = "/v1/authorization"
        body = {
            "client_id": client_id,
            "assertion": assertion,
            "state": "x",  # state is required, but we don't use it
        }
        if scope is not None:
            body["scope"] = scope
        resp = self.apiclient.post(url, body)

        if "redirect" not in resp:
            error_msg = "redirect missing in OAuth response"
            raise OutOfProtocolError(error_msg)

        # This flow is designed for web-based redirects.
        # In order to get the code we must parse it from the redirect url.
        query_params = parse_qs(urlparse(resp["redirect"]).query)
        try:
            return query_params["code"][0]
        except (KeyError, IndexError, ValueError):
            error_msg = "code missing in OAuth redirect url"
            raise OutOfProtocolError(error_msg)

    def authorize_token(self, assertion, scope=None, client_id=None):
        """Trade an identity assertion for an oauth token.

        This method takes an identity assertion for a user and uses it to
        generate an oauth token.  The client_id must have implicit grant
        privileges.

        :param assertion: an identity assertion for the target user.
        :param scope: optional scope to be provided by the token.
        :param client_id: the string generated during FxA client registration.
        """
        if client_id is None:
            client_id = self.client_id
        url = "/v1/authorization"
        body = {
            "client_id": client_id,
            "assertion": assertion,
            "response_type": "token",
            "state": "x",  # state is required, but we don't use it
        }
        if scope is not None:
            body["scope"] = scope
        resp = self.apiclient.post(url, body)

        if 'access_token' not in resp:
            error_msg = 'access_token missing in OAuth response'
            raise OutOfProtocolError(error_msg)

        return resp['access_token']

    def verify_token(self, token, scope=None):
        """Verify an OAuth token, and retrieve user id and scopes.

        :param token: the string to verify.
        :param scope: optional scope expected to be provided for this token.
        :returns: a dict with user id and authorized scopes for this token.
        :raises fxa.errors.ClientError: if the provided token is invalid.
        :raises fxa.errors.TrustError: if the token scopes do not match.
        """
        url = '/v1/verify'
        body = {
            'token': token
        }
        resp = self.apiclient.post(url, body)

        missing_attrs = ", ".join([k for k in ('user', 'scope', 'client_id')
                                   if k not in resp])
        if missing_attrs:
            error_msg = '{0} missing in OAuth response'.format(missing_attrs)
            raise OutOfProtocolError(error_msg)

        if scope is not None:
            authorized_scope = resp['scope']
            if not scope_matches(authorized_scope, scope):
                raise ScopeMismatchError(authorized_scope, scope)

        return resp
