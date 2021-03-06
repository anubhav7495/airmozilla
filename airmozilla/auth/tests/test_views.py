import json

from django.conf import settings
from django.test import TestCase
from django.utils.importlib import import_module

from funfactory.urlresolvers import reverse

import mock
from nose.tools import ok_, eq_

from airmozilla.auth.browserid_mock import mock_browserid
from airmozilla.base import mozillians
from airmozilla.base.tests.testbase import Response
from airmozilla.main.models import UserProfile


VOUCHED_FOR = """
{
  "meta": {
    "previous": null,
    "total_count": 1,
    "offset": 0,
    "limit": 20,
    "next": null
  },
  "objects": [
    {
      "website": "",
      "bio": "",
      "resource_uri": "/api/v1/users/2429/",
      "last_updated": "2012-11-06T14:41:47",
      "groups": [
        "ugly tuna"
      ],
      "city": "Casino",
      "skills": [],
      "country": "Albania",
      "region": "Bush",
      "id": "2429",
      "languages": [],
      "allows_mozilla_sites": true,
      "photo": "http://www.gravatar.com/avatar/0409b497734934400822bb33...",
      "is_vouched": true,
      "email": "peterbe@gmail.com",
      "ircname": "",
      "allows_community_sites": true,
      "full_name": "Peter Bengtsson"
    }
  ]
}
"""

NOT_VOUCHED_FOR = """
{
  "meta": {
    "previous": null,
    "total_count": 1,
    "offset": 0,
    "limit": 20,
    "next": null
  },
  "objects": [
    {
      "website": "http://www.peterbe.com/",
      "bio": "",
      "resource_uri": "/api/v1/users/2430/",
      "last_updated": "2012-11-06T15:37:35",
      "groups": [
        "no beard"
      ],
      "city": "<style>p{font-style:italic}</style>",
      "skills": [],
      "country": "Heard Island and McDonald Islands",
      "region": "Drunk",
      "id": "2430",
      "languages": [],
      "allows_mozilla_sites": true,
      "photo": "http://www.gravatar.com/avatar/23c6d359b6f7af3d3f91ca9e17...",
      "is_vouched": false,
      "email": "tmickel@mit.edu",
      "ircname": "",
      "allows_community_sites": true,
      "full_name": null
    }
  ]
}
"""


class TestViews(TestCase):

    def setUp(self):
        super(TestViews, self).setUp()

        engine = import_module(settings.SESSION_ENGINE)
        store = engine.SessionStore()
        store.save()  # we need to make load() work, or the cookie is worthless
        self.client.cookies[settings.SESSION_COOKIE_NAME] = store.session_key

    def shortDescription(self):
        # Stop nose using the test docstring and instead the test method name.
        pass

    def get_messages(self):
        return self.client.session['_messages']

    def _login_attempt(self, email, assertion='fakeassertion123', next=None):
        if not next:
            next = '/'
        with mock_browserid(email):
            post_data = {
                'assertion': assertion,
                'next': next
            }
            return self.client.post(
                '/browserid/login/',
                post_data
            )

    def test_invalid(self):
        """Bad BrowserID form (i.e. no assertion) -> failure."""
        response = self._login_attempt(None, None)
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL_FAILURE)
        # self.assertRedirects(
        #     response,
        #     settings.LOGIN_REDIRECT_URL_FAILURE + '?bid_login_failed=1'
        # )

    def test_bad_verification(self):
        """Bad verification -> failure."""
        response = self._login_attempt(None)
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL_FAILURE)
        # self.assertRedirects(
        #    response,
        #    settings.LOGIN_REDIRECT_URL_FAILURE + '?bid_login_failed=1'
        # )

    @mock.patch('requests.get')
    def test_nonmozilla(self, rget):
        """Non-Mozilla email -> failure."""
        def mocked_get(url, **options):
            if 'tmickel' in url:
                return Response(NOT_VOUCHED_FOR)
            if 'peterbe' in url:
                return Response(VOUCHED_FOR)
            raise NotImplementedError(url)
        rget.side_effect = mocked_get

        response = self._login_attempt('tmickel@mit.edu')
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL_FAILURE)
        # self.assertRedirects(
        #     response,
        #     settings.LOGIN_REDIRECT_URL_FAILURE + '?bid_login_failed=1'
        # )

        # now with a non-mozillian that is vouched for
        response = self._login_attempt('peterbe@gmail.com')
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL)
        # self.assertRedirects(response,
        #                      settings.LOGIN_REDIRECT_URL)

    @mock.patch('requests.get')
    def test_nonmozilla_vouched_for_second_time(self, rget):
        assert not UserProfile.objects.all()

        def mocked_get(url, **options):
            return Response(VOUCHED_FOR)

        rget.side_effect = mocked_get

        # now with a non-mozillian that is vouched for
        response = self._login_attempt('peterbe@gmail.com')
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL)
        # self.assertRedirects(response,
        #                      settings.LOGIN_REDIRECT_URL)

        # should be logged in
        response = self.client.get('/')
        eq_(response.status_code, 200)
        ok_('Sign in' not in response.content)
        ok_('Sign out' in response.content)

        profile, = UserProfile.objects.all()
        ok_(profile.contributor)

        # sign out
        response = self.client.get(reverse('browserid.logout'))
        eq_(response.status_code, 405)
        response = self.client.post(reverse('browserid.logout'))
        eq_(response.status_code, 200)
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL)

        # should be logged out
        response = self.client.get('/')
        eq_(response.status_code, 200)
        ok_('Sign in' in response.content)
        ok_('Sign out' not in response.content)

        # sign in again
        response = self._login_attempt('peterbe@gmail.com')
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL)
        # self.assertRedirects(response,
        #                      settings.LOGIN_REDIRECT_URL)
        # should not have created another one
        eq_(UserProfile.objects.all().count(), 1)

        # sign out again
        response = self.client.post(reverse('browserid.logout'))
        eq_(response.status_code, 200)
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL)

        # pretend this is lost
        profile.contributor = False
        profile.save()
        response = self._login_attempt('peterbe@gmail.com')
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL)

        # self.assertRedirects(response,
        #                      settings.LOGIN_REDIRECT_URL)
        # should not have created another one
        eq_(UserProfile.objects.filter(contributor=True).count(), 1)

    def test_mozilla(self):
        """Mozilla email -> success."""
        # Try the first allowed domain
        response = self._login_attempt('tmickel@' + settings.ALLOWED_BID[0])
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL)
        # self.assertRedirects(response,
        #                      settings.LOGIN_REDIRECT_URL)

    @mock.patch('requests.get')
    def test_was_contributor_now_mozilla_bid(self, rget):
        """Suppose a user *was* a contributor but now her domain name
        is one of the allowed ones, it should undo that contributor status
        """
        assert not UserProfile.objects.all()

        def mocked_get(url, **options):
            return Response(VOUCHED_FOR)

        rget.side_effect = mocked_get
        response = self._login_attempt('peterbe@gmail.com')
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL)

        response = self.client.get('/')
        eq_(response.status_code, 200)
        ok_('Sign in' not in response.content)
        ok_('Sign out' in response.content)

        profile = UserProfile.objects.get(user__email='peterbe@gmail.com')
        ok_(profile.contributor)

        self.client.logout()
        response = self.client.get('/')
        eq_(response.status_code, 200)
        ok_('Sign in' in response.content)
        ok_('Sign out' not in response.content)

        with self.settings(ALLOWED_BID=settings.ALLOWED_BID + ('gmail.com',)):
            response = self._login_attempt('peterbe@gmail.com')
            eq_(response['content-type'], 'application/json')
            redirect = json.loads(response.content)['redirect']
            eq_(redirect, settings.LOGIN_REDIRECT_URL)

        profile = UserProfile.objects.get(user__email='peterbe@gmail.com')
        ok_(not profile.contributor)  # fixed!

    @mock.patch('airmozilla.auth.views.logger')
    @mock.patch('requests.get')
    def test_nonmozilla_mozillians_unhappy(self, rget, rlogger):
        assert not UserProfile.objects.all()

        def mocked_get(url, **options):
            raise mozillians.BadStatusCodeError('crap!')

        rget.side_effect = mocked_get

        # now with a non-mozillian that is vouched for
        response = self._login_attempt('peterbe@gmail.com')
        eq_(response['content-type'], 'application/json')
        redirect = json.loads(response.content)['redirect']
        eq_(redirect, settings.LOGIN_REDIRECT_URL_FAILURE)
        # self.assertRedirects(
        #     response,
        #     settings.LOGIN_REDIRECT_URL_FAILURE + '?bid_login_failed=1'
        # )
        eq_(rlogger.error.call_count, 1)
