import logging
import itertools
from operator import itemgetter
from typing import List, Dict

from lbry.schema.url import URL
from lbry.schema.result import Outputs as ResultOutput
from lbry.error import ResolveCensoredError
from lbry.blockchain.transaction import Output

from ..query_context import context
from .search import search_claims


log = logging.getLogger(__name__)


def _get_referenced_rows(txo_rows: List[dict], censor_channels: List[bytes]):
    # censor = context().get_resolve_censor()
    repost_hashes = set(filter(None, map(itemgetter('reposted_claim_hash'), txo_rows)))
    channel_hashes = set(itertools.chain(
        filter(None, map(itemgetter('channel_hash'), txo_rows)),
        censor_channels
    ))

    reposted_txos = []
    if repost_hashes:
        reposted_txos = search_claims(**{'claim.claim_hash__in': repost_hashes})
        channel_hashes |= set(filter(None, map(itemgetter('channel_hash'), reposted_txos)))

    channel_txos = []
    if channel_hashes:
        channel_txos = search_claims(**{'claim.claim_hash__in': channel_hashes})

    # channels must come first for client side inflation to work properly
    return channel_txos + reposted_txos


def protobuf_resolve(urls, **kwargs) -> str:
    return ResultOutput.to_base64([resolve_url(raw_url) for raw_url in urls], [])


def resolve(urls, **kwargs) -> Dict[str, Output]:
    return {url: resolve_url(url) for url in urls}
    #txo_rows = [resolve_url(raw_url) for raw_url in urls]
    #extra_txo_rows = _get_referenced_rows(
    #    [txo for txo in txo_rows if isinstance(txo, dict)],
    #    [txo.censor_hash for txo in txo_rows if isinstance(txo, ResolveCensoredError)]
    #)
    #return txo_rows, extra_txo_rows


def resolve_url(raw_url):
    censor = context().get_resolve_censor()

    try:
        url = URL.parse(raw_url)
    except ValueError as e:
        return e

    channel = None

    if url.has_channel:
        q = url.channel.to_dict()
        if set(q) == {'name'}:
            q['is_controlling'] = True
        else:
            q['order_by'] = ['^creation_height']
        #matches = search_claims(censor, **q, limit=1)
        matches = search_claims(**q, limit=1)[0]
        if matches:
            channel = matches[0]
        elif censor.censored:
            return ResolveCensoredError(raw_url, next(iter(censor.censored)))
        else:
            return LookupError(f'Could not find channel in "{raw_url}".')

    if url.has_stream:
        q = url.stream.to_dict()
        if channel is not None:
            q['order_by'] = ['^creation_height']
            q['channel_hash'] = channel.claim_hash
            q['is_signature_valid'] = True
        elif set(q) == {'name'}:
            q['is_controlling'] = True
        # matches = search_claims(censor, **q, limit=1)
        matches = search_claims(**q, limit=1)[0]
        if matches:
            return matches[0]
        elif censor.censored:
            return ResolveCensoredError(raw_url, next(iter(censor.censored)))
        else:
            return LookupError(f'Could not find claim at "{raw_url}".')

    return channel