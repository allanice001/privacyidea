# -*- coding: utf-8 -*-
#
#  2016-05-04 Cornelius Kölbel <cornelius.koelbel@netknights.it>
#             Initial writup
#
# License:  AGPLv3
# (c) 2016. Cornelius Kölbel
#
# This code is free software; you can redistribute it and/or
# modify it under the terms of the GNU AFFERO GENERAL PUBLIC LICENSE
# License as published by the Free Software Foundation; either
# version 3 of the License, or any later version.
#
# This code is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU AFFERO GENERAL PUBLIC LICENSE for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#
__doc__ = """This is the base class for an event handler module.
The event handler module is bound to an event together with

* a condition and
* an action
* optional options ;-)
"""
from gettext import gettext as _
from privacyidea.lib.config import get_token_types
from privacyidea.lib.realm import get_realms
from privacyidea.lib.auth import ROLE
from privacyidea.lib.token import get_token_owner, get_tokens
from privacyidea.lib.user import User
import re
import json
import logging

log = logging.getLogger(__name__)


class CONDITION(object):
    """
    Possible conditions
    """
    TOKEN_HAS_OWNER = "token_has_owner"
    TOKEN_IS_ORPHANED = "token_is_orphaned"


class BaseEventHandler(object):
    """
    An Eventhandler needs to return a list of actions, which it can handle.

    It also returns a list of allowed action and conditions

    It returns an identifier, which can be used in the eventhandlig definitions
    """

    identifier = "BaseEventHandler"
    description = "This is the base class of an EventHandler with no " \
                  "functionality"

    def __init__(self):
        pass

    @property
    def actions(cls):
        """
        This method returns a list of available actions, that are provided
        by this event handler.
        :return: dictionary of actions.
        """
        actions = ["sample_action_1", "sample_action_2"]
        return actions

    @property
    def conditions(cls):
        """
        The UserNotification can filter for conditions like
        * type of logged in user and
        * successful or failed value.success

        allowed types are str, multi, text, regexp

        :return: dict
        """
        realms = get_realms()
        cond = {
            "realm": {
                "type": "str",
                "desc": _("The user realm, for which this event should apply."),
                "value": realms.keys()
            },
            "tokenrealm": {
                "type": "multi",
                "desc": _("The token realm, for which this event should "
                          "apply."),
                "value": [{"name": r} for r in realms.keys()]
            },
            "tokentype": {
                "type": "multi",
                "desc": _("The type of the token."),
                "value": [{"name": r} for r in get_token_types()]
            },
            "logged_in_user": {
                "type": "str",
                "desc": _("The logged in user is of the following type."),
                "value": (ROLE.ADMIN, ROLE.USER)
            },
            "result_value": {
                "type": "str",
                "desc": _("The result.value within the response is "
                          "True or False."),
                "value": ("True", "False")
            },
            "token_locked": {
                "type": "str",
                "desc": _("Check if the max failcounter of the token is "
                          "reached."),
                "value": ("True", "False")
            },
            CONDITION.TOKEN_HAS_OWNER: {
                "type": "str",
                "desc": _("The token has a user assigned."),
                "value": ("True", "False")
            },
            CONDITION.TOKEN_IS_ORPHANED: {
                "type": "str",
                "desc": _("The token has a user assigned, but the user does "
                          "not exist in the userstore anymore."),
                "value": ("True", "False")
            },
            "serial": {
                "type": "regexp",
                "desc": _("Action is triggered, if the serial matches this "
                          "regular expression.")
            }
        }
        return cond

    @property
    def events(cls):
        """
        This method returns a list allowed events, that this event handler
        can be bound to and which it can handle with the corresponding actions.

        An eventhandler may return an asterisk ["*"] indicating, that it can
        be used in all events.
        :return: list of events
        """
        events = ["*"]
        return events

    @staticmethod
    def _get_tokenowner(request):
        user = request.User
        serial = request.all_data.get("serial")
        if user.is_empty() and serial:
            # maybe the user is empty, but a serial was passed.
            # Then we determine the user by the serial
            user = get_token_owner(serial) or User()
        return user

    def check_condition(self, options):
        """
        Check if all conditions are met and if the action should be executed.
        The the conditions are met, we return "True"
        :return: True
        """
        res = True
        g = options.get("g")
        request = options.get("request")
        response = options.get("response")
        e_handler_def = options.get("handler_def")
        if not response or not e_handler_def:
            # options is missing a response and the handler definition
            # We are probably in test mode.
            return True
        # conditions can be correspnding to the property conditions
        conditions = e_handler_def.get("conditions")
        content = json.loads(response.data)
        user = self._get_tokenowner(request)

        serial = request.all_data.get("serial") or \
                 content.get("detail", {}).get("serial")
        token_obj_list = get_tokens(serial=serial)
        tokenrealms = []
        tokentype = None
        token_obj = None
        if token_obj_list:
            token_obj = token_obj_list[0]
            tokenrealms = token_obj.get_realms()
            tokentype = token_obj.get_tokentype()

        if "realm" in conditions:
            res = user.realm == conditions.get("realm")

        if "logged_in_user" in conditions and res:
            # Determine the role of the user
            try:
                logged_in_user = g.logged_in_user
                user_role = logged_in_user.get("role")
            except Exception:
                # A non-logged-in-user is a User, not an admin
                user_role = ROLE.USER
            res = user_role == conditions.get("logged_in_user")

        # Check result_value only if the check condition is still True
        if "result_value" in conditions and res:
            res = content.get("result", {}).get("value") == conditions.get(
                "result_value")

        # checking of max-failcounter state of the token
        if "token_locked" in conditions and res:
            if token_obj:
                locked = token_obj.get_failcount() >= \
                         token_obj.get_max_failcount()
                res = (conditions.get("token_locked") in ["True", True]) == \
                      locked
            else:
                # check all tokens of the user, if any token is maxfail
                token_objects = get_tokens(user=user, maxfail=True)
                if not ','.join([tok.get_serial() for tok in token_objects]):
                    res = False

        if "tokenrealm" in conditions and res:
            if tokenrealms:
                res = False
                for trealm in tokenrealms:
                    if trealm in conditions.get("tokenrealm").split(","):
                        res = True
                        break

        if "tokentype" in conditions and res:
            if tokentype:
                res = False
                if tokentype in conditions.get("tokentype").split(","):
                    res = True

        if "serial" in conditions and res:
            serial_match = conditions.get("serial")
            if serial:
                res = bool(re.match(serial_match, serial))

        if CONDITION.TOKEN_HAS_OWNER in conditions and res and token_obj:
            uid = token_obj.get_user_id()
            check = conditions.get(CONDITION.TOKEN_HAS_OWNER)
            if uid and check in ["True", True]:
                res = True
            elif not uid and check in ["False", False]:
                res = True
            else:
                log.debug("Condition token_has_owner for token {0!r} "
                          "failed.".format(token_obj))
                res = False

        return res

    def do(self, action, options=None):
        """
        This method executes the defined action in the given event.

        :param action:
        :param options: Contains the flask parameters g and request and the
            handler_def configuration
        :type options: dict
        :return:
        """
        log.info("In fact we are doing nothing, be we presume we are doing"
                 "{0!s}".format(action))
        return True
