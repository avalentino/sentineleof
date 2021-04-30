"""sentinelsat based client to get orbit files form scihub.copernicu.eu."""


import re
import logging
import datetime
import operator
import collections
from typing import NamedTuple, Sequence

from ._gnss import GnssAPI
from .products import Sentinel as S1Product


_log = logging.getLogger(__name__)


DATE_FMT = '%Y%m%dT%H%M%S'


class ValidityError(ValueError):
    pass


class ValidityInfo(NamedTuple):
    product_id: str
    generation_date: datetime.datetime
    start_validity: datetime.datetime
    stop_validity: datetime.datetime


def get_validity_info(products: Sequence[str],
                      pattern=None) -> Sequence[ValidityInfo]:
    if pattern is None:
        # use a generic pattern
        pattern = re.compile(
            r'S1\w+_(?P<generation_date>\d{8}T\d{6})_'
            r'V(?P<start_validity>\d{8}T\d{6})_'
            r'(?P<stop_validity>\d{8}T\d{6})\w*')

    keys = ('generation_date', 'start_validity', 'stop_validity')
    out = []
    for product_id in products:
        mobj = pattern.match(product_id)
        if mobj:
            validity_data = {
                name: datetime.datetime.strptime(mobj.group(name), DATE_FMT)
                for name in keys
            }
            out.append(ValidityInfo(product_id, **validity_data))
        else:
            raise ValueError(
                f'"{product_id}" does not math the regular expression '
                f'for validity')

    return out


def lastval_cover(t0: datetime.datetime, t1: datetime.datetime,
                  data: Sequence[ValidityInfo]) -> str:
    candidates = [
        item for item in data
        if item.start_validity <= t0 and item.stop_validity >= t1
    ]
    if not candidates:
        raise ValidityError(
            f'none of the input products completely covers the requested '
            f'time interval: [t0={t0}, t1={t1}]')

    candidates.sort(key=operator.attrgetter('generation_date'), reverse=True)

    return candidates[0].product_id


class OrbitSelectionError(RuntimeError):
    pass


class ScihubGnssClient:
    T0 = datetime.timedelta(days=1)
    T1 = datetime.timedelta(days=1)

    def __init__(self, **kwargs):
        self._api = GnssAPI(**kwargs)

    def query_orbit(self, t0, t1, satellite_id: str,
                    product_type: str = 'AUX_POEORB'):
        assert satellite_id in {'S1A', 'S1B'}
        assert product_type in {'AUX_POEORB', 'AUX_RESORB'}

        query_padams = dict(
            producttype=product_type,
            platformserialidentifier=satellite_id[1:],
            date=[t0, t1],
        )
        _log.debug('query parameter: %s', query_padams)
        products = self._api.query(**query_padams)
        return products

    @staticmethod
    def _select_orbit(products, t0, t1):
        orbit_products = [p['identifier'] for p in products.values()]
        validity_info = get_validity_info(orbit_products)
        product_id = lastval_cover(t0, t1, validity_info)
        return collections.OrderedDict(
            (k, v) for k, v in products.items()
            if v['identifier'] == product_id
        )

    def query_orbit_for_product(self, product,
                                product_type: str = 'AUX_POEORB',
                                t0_margin: datetime.timedelta = T0,
                                t1_margin: datetime.timedelta = T1):
        if isinstance(product, str):
            product = S1Product(product)

        t0 = product.start_time
        t1 = product.stop_time

        products = self.query_orbit(t0 - t0_margin, t1 + t1_margin,
                                    satellite_id=product.mission,
                                    product_type=product_type)
        return self._select_orbit(products, t0, t1)

    def download(self, uuid, **kwargs):
        """Download a single orbit product.

        See sentinelsat.SentinelAPI.download for a detailed desctiption
        of arguments.
        """
        return self._api.download(uuid, **kwargs)

    def download_all(self, products, **kwargs):
        """Download all the specified orbit products.

        See sentinelsat.SentinelAPI.download_all for a detailed desctiption
        of arguments.
        """
        return self._api.download_all(products, **kwargs)


if __name__ == '__main__':
    import argparse

    logging.basicConfig(format='%(levelname)s: %(message)s')
    logging.getLogger(__name__).setLevel(logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument('products', metavar='PRODUCT', nargs='+')

    args = parser.parse_args()

    client = ScihubGnssClient()
    client._api.logger.setLevel(logging.DEBUG)

    query = {}
    for product in args.products:
        query.update(client.query_orbit_for_product(product))

    assert len(query) == len(args.products)

    client.download_all(query)
