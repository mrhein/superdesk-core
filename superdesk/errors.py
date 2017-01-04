# -*- coding: utf-8; -*-
#
# This file is part of Superdesk.
#
# Copyright 2013, 2014 Sourcefabric z.u. and contributors.
#
# For the full copyright and license information, please see the
# AUTHORS and LICENSE files distributed with this source code, or
# at https://www.sourcefabric.org/superdesk/license

import logging

from flask import current_app as app
from eve.validation import ValidationError


logger = logging.getLogger(__name__)
notifiers = []


def add_notifier(notifier):
    if notifier not in notifiers:
        notifiers.append(notifier)


def update_notifiers(*args, **kwargs):
    for notifier in notifiers:
        notifier(*args, **kwargs)


def get_registered_errors(self):
    return {
        'IngestApiError': IngestApiError._codes,
        'IngestFtpError': IngestFtpError._codes,
        'IngestFileError': IngestFileError._codes
    }


def log_exception(msg):
    """Log exception if handling exception, error otherwise."""
    try:
        logger.exception(msg)
    except AttributeError:
        # there is attribute error in python3.4 in case there is no exception context
        logger.error(msg)


class SuperdeskError(ValidationError):
    _codes = {}
    system_exception = None

    def __init__(self, code, desc=None):
        #: numeric error code
        self.code = code

        #: optional detailed error description, defaults to None
        self.desc = desc

        self.message = self._codes.get(code, 'Unknown error')

    def __str__(self):
        desc_text = '' if not self.desc else (' Details: ' + self.desc)
        return "{} Error {} - {}{desc}".format(
            self.__class__.__name__,
            self.code,
            self.message,
            desc=desc_text
        )

    def get_error_description(self):
        return self.code, self._codes[self.code]


class SuperdeskApiError(SuperdeskError):
    """Base class for superdesk API."""

    #: error status code
    status_code = 400

    def __init__(self, message=None, status_code=None, payload=None, exception=None):
        Exception.__init__(self)

        #: a human readable error description
        self.message = message

        if status_code:
            self.status_code = status_code

        if payload:
            self.payload = payload

        if exception:
            logger.exception(message or exception)
        elif message:
            logger.error("HTTP Exception {} has been raised: {}".format(status_code, message))

    def to_dict(self):
        """Create dict for json response."""
        rv = {}
        rv[app.config['STATUS']] = app.config['STATUS_ERR']
        rv['_message'] = self.message or ''
        if hasattr(self, 'payload'):
            rv[app.config['ISSUES']] = self.payload
        return rv

    def __str__(self):
        return "{}: {}".format(repr(self.status_code), self.message)

    @classmethod
    def badRequestError(cls, message=None, payload=None, exception=None):
        return SuperdeskApiError(status_code=400, message=message, payload=payload, exception=exception)

    @classmethod
    def unauthorizedError(cls, message=None, payload={'auth': 1}, exception=None):
        return SuperdeskApiError(status_code=401, message=message, payload=payload, exception=exception)

    @classmethod
    def forbiddenError(cls, message=None, payload=None, exception=None):
        return SuperdeskApiError(status_code=403, message=message, payload=payload, exception=exception)

    @classmethod
    def notFoundError(cls, message=None, payload=None, exception=None):
        return SuperdeskApiError(status_code=404, message=message, payload=payload, exception=exception)

    @classmethod
    def preconditionFailedError(cls, message=None, payload=None, exception=None):
        return SuperdeskApiError(status_code=412, message=message, payload=payload, exception=exception)

    @classmethod
    def internalError(cls, message=None, payload=None, exception=None):
        return SuperdeskApiError(status_code=500, message=message, payload=payload, exception=exception)


class IdentifierGenerationError(SuperdeskApiError):
    """Exception raised if failed to generate unique_id."""

    status_code = 500
    payload = {'unique_id': 1}
    message = "Failed to generate unique_id"


class InvalidFileType(SuperdeskError):
    """Exception raised when receiving a file type that is not supported."""

    def __init__(self, type=None):
        super().__init__('Invalid file type %s' % type, payload={})


class BulkIndexError(SuperdeskError):
    """Exception raised when bulk index operation fails.."""

    def __init__(self, resource=None, errors=None):
        super().__init__('Failed to bulk index resource {} errors: {}'.format(resource, errors), payload={})


class PrivilegeNameError(Exception):
    pass


class InvalidStateTransitionError(SuperdeskApiError):
    """Exception raised if workflow transition is invalid."""

    def __init__(self, message='Workflow transition is invalid.', status_code=412):
        super().__init__(message, status_code)


class SuperdeskIngestError(SuperdeskError):
    _codes = {
        2000: 'Configured Feed Parser either not found or not registered with the application'
    }

    def __init__(self, code, exception, provider=None):
        super().__init__(code)
        self.system_exception = exception
        provider = provider or {}
        self.provider_name = provider.get('name', 'Unknown provider') if provider else 'Unknown provider'

        if exception:
            if provider.get('notifications', {}).get('on_error', True):
                exception_msg = str(exception)[-200:]
                update_notifiers('error',
                                 'Error [%s] on ingest provider {{name}}: %s' % (code, exception_msg),
                                 resource='ingest_providers' if provider else None,
                                 name=self.provider_name,
                                 provider_id=provider.get('_id', ''))

            if provider:
                log_exception("{}: {} on channel {}".format(self, exception, self.provider_name))
            else:
                log_exception("{}: {}".format(self, exception))

    @classmethod
    def parserNotFoundError(cls, exception=None, provider=None):
        return SuperdeskIngestError(2000, exception, provider)


class ProviderError(SuperdeskIngestError):
    _codes = {
        2001: 'Provider could not be saved',
        2002: 'Expired content could not be removed',
        2003: 'Rule could not be applied',
        2004: 'Ingest error',
        2005: 'Anpa category error',
        2006: 'Expired content could not be filtered',
        2007: 'IPTC processing error',
        2008: 'External source no suitable resolution found'
    }

    @classmethod
    def providerAddError(cls, exception=None, provider=None):
        return ProviderError(2001, exception, provider)

    @classmethod
    def expiredContentError(cls, exception=None, provider=None):
        return ProviderError(2002, exception, provider)

    @classmethod
    def ruleError(cls, exception=None, provider=None):
        return ProviderError(2003, exception, provider)

    @classmethod
    def ingestError(cls, exception=None, provider=None):
        return ProviderError(2004, exception, provider)

    @classmethod
    def anpaError(cls, exception=None, provider=None):
        return ProviderError(2005, exception, provider)

    @classmethod
    def providerFilterExpiredContentError(cls, exception=None, provider=None):
        return ProviderError(2006, exception, provider)

    @classmethod
    def iptcError(cls, exception=None, provider=None):
        return ProviderError(2007, exception, provider)

    @classmethod
    def externalProviderError(cls, exception=None, provider=None):
        return ProviderError(2008, exception, provider)


class ParserError(SuperdeskIngestError):
    _codes = {
        1001: 'Message could not be parsed',
        1002: 'Ingest file could not be parsed',
        1003: 'ANPA file could not be parsed',
        1004: 'NewsML1 input could not be processed',
        1005: 'NewsML2 input could not be processed',
        1006: 'NITF input could not be processed',
        1007: 'WENN input could not be processed',
        1008: 'IPTC7901 input could not be processed'
    }

    @classmethod
    def parseMessageError(cls, exception=None, provider=None):
        return ParserError(1001, exception, provider)

    @classmethod
    def parseFileError(cls, source=None, filename=None, exception=None, provider=None):
        if source and filename:
            log_exception("Source Type: {} - File: {} could not be processed".format(source, filename))
        return ParserError(1002, exception, provider)

    @classmethod
    def anpaParseFileError(cls, filename=None, exception=None):
        if filename:
            logger.error("File: {} could not be processed".format(filename))
        return ParserError(1003, exception)

    @classmethod
    def newsmlOneParserError(cls, exception=None, provider=None):
        return ParserError(1004, exception, provider)

    @classmethod
    def newsmlTwoParserError(cls, exception=None, provider=None):
        return ParserError(1005, exception, provider)

    @classmethod
    def nitfParserError(cls, exception=None, provider=None):
        return ParserError(1006, exception, provider)

    @classmethod
    def wennParserError(cls, exception=None, provider=None):
        return ParserError(1007, exception, provider)

    @classmethod
    def IPTC7901ParserError(cls, exception=None, provider=None):
        return ParserError(1008, exception, provider)


class IngestFileError(SuperdeskIngestError):
    _codes = {
        3001: 'Destination folder could not be created',
        3002: 'Ingest file could not be copied'
    }

    @classmethod
    def folderCreateError(cls, exception=None, provider=None):
        return IngestFileError(3001, exception, provider)

    @classmethod
    def fileMoveError(cls, exception=None, provider=None):
        return IngestFileError(3002, exception, provider)


class IngestApiError(SuperdeskIngestError):
    _codes = {
        4000: "Unknown API ingest error",
        4001: "API ingest connection has timed out.",
        4002: "API ingest has too many redirects",
        4003: "API ingest has request error",
        4004: "API ingest Unicode Encode Error",
        4005: 'API ingest xml parse error',
        4006: 'API service not found(404) error',
        4007: 'API authorization error',
        4008: 'Authentication URL is missing from Ingest Provider configuraion'
    }

    @classmethod
    def apiGeneralError(cls, exception=None, provider=None):
        return cls(4000, exception, provider)

    @classmethod
    def apiTimeoutError(cls, exception=None, provider=None):
        return cls(4001, exception, provider)

    @classmethod
    def apiRedirectError(cls, exception=None, provider=None):
        return cls(4002, exception, provider)

    @classmethod
    def apiRequestError(cls, exception=None, provider=None):
        return cls(4003, exception, provider)

    @classmethod
    def apiUnicodeError(cls, exception=None, provider=None):
        return cls(4004, exception, provider)

    @classmethod
    def apiParseError(cls, exception=None, provider=None):
        return cls(4005, exception, provider)

    @classmethod
    def apiNotFoundError(cls, exception=None, provider=None):
        return cls(4006, exception, provider)

    @classmethod
    def apiAuthError(cls, exception=None, provider=None):
        return cls(4007, exception, provider)


class IngestFtpError(SuperdeskIngestError):
    _codes = {
        5000: "FTP ingest error",
        5001: "FTP parser could not be found"
    }

    @classmethod
    def ftpError(cls, exception=None, provider=None):
        return IngestFtpError(5000, exception, provider)

    @classmethod
    def ftpUnknownParserError(cls, exception=None, provider=None, filename=None):
        if provider:
            logger.error("Provider: {} - File: {} unknown file format. "
                         "FeedParser couldn't be found.".format(provider.get('name', 'Unknown provider'), filename))
        return IngestFtpError(5001, exception, provider)


class IngestEmailError(SuperdeskIngestError):
    _codes = {
        6000: "Email authentication failure",
        6001: "Email parse error",
        6002: "Email ingest error"
    }

    @classmethod
    def emailLoginError(cls, exception=None, provider=None):
        return IngestEmailError(6000, exception, provider)

    @classmethod
    def emailParseError(cls, exception=None, provider=None):
        return IngestEmailError(6001, exception, provider)

    @classmethod
    def emailError(cls, exception=None, provider=None):
        return IngestEmailError(6002, exception, provider)


class SuperdeskPublishError(SuperdeskError):
    def __init__(self, code, exception, destination=None):
        super().__init__(code)
        self.system_exception = exception
        destination = destination or {}
        self.destination_name = destination.get('name', 'Unknown destination') if destination else 'Unknown destination'

        if exception:
            exception_msg = str(exception)[-200:]
            update_notifiers('error',
                             'Error [%s] on a Subscriber''s destination {{name}}: %s' % (code, exception_msg),
                             resource='subscribers' if destination else None,
                             name=self.destination_name,
                             provider_id=destination.get('_id', ''))

            if destination:
                log_exception("{}: {} on destination {}".format(self, exception, self.destination_name))
            else:
                log_exception("{}: {}".format(self, exception))


class FormatterError(SuperdeskPublishError):
    _codes = {
        7001: 'Article couldn"t be converted to NITF format',
        7002: 'Article couldn"t be converted to AAP IPNews format',
        7003: 'Article couldn"t be converted to ANPA',
        7004: 'Article couldn"t be converted to NinJS',
        7005: 'Article couldn"t be converted to NewsML 1.2 format',
        7006: 'Article couldn"t be converted to NewsML G2 format',
        7008: 'Article couldn"t be converted to AAP SMS format',
        7009: 'Article couldn"t be converted to AAP Newscentre',
        7010: 'Article couldn"t be converted to Email'
    }

    @classmethod
    def nitfFormatterError(cls, exception=None, destination=None):
        return FormatterError(7001, exception, destination)

    @classmethod
    def AAPIpNewsFormatterError(clscls, exception=None, destination=None):
        return FormatterError(7002, exception, destination)

    @classmethod
    def AnpaFormatterError(cls, exception=None, destination=None):
        return FormatterError(7003, exception, destination)

    @classmethod
    def ninjsFormatterError(cls, exception=None, destination=None):
        return FormatterError(7004, exception, destination)

    @classmethod
    def newml12FormatterError(cls, exception=None, destination=None):
        return FormatterError(7005, exception, destination)

    @classmethod
    def newmsmlG2FormatterError(cls, exception=None, destination=None):
        return FormatterError(7006, exception, destination)

    @classmethod
    def bulletinBuilderFormatterError(cls, exception=None, destination=None):
        return FormatterError(7007, exception, destination)

    @classmethod
    def AAPSMSFormatterError(cls, exception=None, destination=None):
        return FormatterError(7008, exception, destination)

    @classmethod
    def AAPNewscentreFormatterError(cls, exception=None, destination=None):
        return FormatterError(7009, exception, destination)

    @classmethod
    def EmailFormatterError(cls, exception=None, destination=None):
        return FormatterError(7010, exception, destination)


class SubscriberError(SuperdeskPublishError):
    _codes = {
        8001: 'Subscriber is closed'
    }

    @classmethod
    def subscriber_inactive_error(cls, exception=None, destination=None):
        return FormatterError(8001, exception, destination)


class PublishQueueError(SuperdeskPublishError):
    _codes = {
        9001: 'Item could not be updated in the queue',
        9002: 'Item format could not be recognized',
        9004: 'Schedule information could not be processed',
        9005: 'State of the content item could not be updated',
        9007: 'Previous take is either not published or killed',
        9008: 'A post-publish action has happened on item',
        9009: 'Item could not be queued'
    }

    @classmethod
    def item_update_error(cls, exception=None, destination=None):
        return PublishQueueError(9001, exception, destination)

    @classmethod
    def unknown_format_error(cls, exception=None, destination=None):
        return PublishQueueError(9002, exception, destination)

    @classmethod
    def bad_schedule_error(cls, exception=None, destination=None):
        return PublishQueueError(9004, exception, destination)

    @classmethod
    def content_update_error(cls, exception=None, destination=None):
        return PublishQueueError(9005, exception, destination)

    @classmethod
    def previous_take_not_published_error(cls, exception=None, destination=None):
        return PublishQueueError(9007, exception, destination)

    @classmethod
    def post_publish_exists_error(cls, exception=None, destination=None):
        return PublishQueueError(9008, exception, destination)

    @classmethod
    def item_not_queued_error(cls, exception=None, destination=None):
        return PublishQueueError(9009, exception, destination)

    @classmethod
    def article_not_found_error(cls, exception=None, destination=None):
        return PublishQueueError(9010, exception, destination)


class PublishFtpError(SuperdeskPublishError):
    _codes = {
        10000: "FTP publish error"
    }

    @classmethod
    def ftpError(cls, exception=None, destination=None):
        return PublishFtpError(10000, exception, destination)


class PublishEmailError(SuperdeskPublishError):
    _codes = {
        11000: "Email publish error",
        11001: "Recipient could not be found for destination"
    }

    @classmethod
    def emailError(cls, exception=None, destination=None):
        return PublishEmailError(11000, exception, destination)

    @classmethod
    def recipientNotFoundError(cls, exception=None, destination=None):
        return PublishEmailError(11001, exception, destination)


class PublishODBCError(SuperdeskPublishError):
    _codes = {
        12000: "ODBC publish error"
    }

    @classmethod
    def odbcError(cls, exception=None, destination=None):
        return PublishODBCError(12000, exception, destination)


class PublishFileError(SuperdeskPublishError):
    _codes = {
        13000: "File publish error"
    }

    @classmethod
    def fileSaveError(cls, exception=None, destinations=None):
        return PublishFileError(13000, exception, destinations)


class PublishHTTPPushError(SuperdeskPublishError):
    _codes = {
        14000: "HTTP push publish error",
    }

    @classmethod
    def httpPushError(cls, exception=None, destination=None):
        return PublishHTTPPushError(14000, exception, destination)


class PublishHTTPPushClientError(PublishHTTPPushError):
    _codes = {
        14001: "HTTP push publish client error",
    }

    @classmethod
    def httpPushError(cls, exception=None, destination=None):
        return PublishHTTPPushClientError(14001, exception, destination)


class PublishHTTPPushServerError(PublishHTTPPushError):
    _codes = {
        14002: "HTTP push publish server error",
    }

    @classmethod
    def httpPushError(cls, exception=None, destination=None):
        return PublishHTTPPushServerError(14002, exception, destination)


class AlreadyExistsError(Exception):
    pass
