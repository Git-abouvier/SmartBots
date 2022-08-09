""" Load data from DB and create Events for consumption by portfolio engine """
import os
import pandas as pd
import numpy as np
import datetime as dt
from smartbots.events import Bar
from arctic import Arctic, CHUNK_STORE
from typing import List, Dict
from smartbots.decorators import log_start_end
from smartbots import conf
import calendar
from dateutil import relativedelta


def load_tickers_and_create_events(symbols_lib_name: list, start_date: dt.datetime = dt.datetime(2022, 1, 1),
                                   end_date: dt.datetime= dt.datetime.utcnow()):
    """ Load data from DB and create Events for consumption by portfolio engine
        symbols_lib_name: list of symbols to load with info about the source of the data
        start_date: start date of the query period
        end_date: end date of the query period """

    store = Arctic(f'{conf.MONGO_HOST}:{conf.MONGO_PORT}', username=conf.MONGO_INITDB_ROOT_USERNAME,
                   password=conf.MONGO_INITDB_ROOT_PASSWORD)

    from_month = start_date
    end_month = calendar.monthrange(from_month.year, from_month.month)
    to_month = dt.datetime(from_month.year, from_month.month, end_month[1], 23, 59)

    events = []
    while True:
        for info in symbols_lib_name:
            symbol = info['ticker']
            name_library = info['historical_library']
            print(f'{symbol} {str(from_month)}')
            lib = store[name_library]
            data = lib.read(symbol, chunk_range=pd.date_range(from_month,
                                                               to_month + dt.timedelta(days=1)))
            if data is not None:
                data = data[data.index <= to_month]

            for tuple in data.itertuples():
                events.append(Bar(datetime=tuple.Index, ticker=symbol, open=tuple.open, high=tuple.high,
                                  low=tuple.low, close=tuple.close, volume=tuple.volume))
        if len(events) == 0:
            break

        ### Order and Send events to portfolio engine
        for b in sorted(events, key=lambda x: x.datetime, reverse=False):
            yield {'bar': b}

        # Actualizamos
        from_month = from_month + relativedelta.relativedelta(months=1)
        from_month = dt.datetime(from_month.year, from_month.month, 1) # first day of the month
        end_month = calendar.monthrange(from_month.year, from_month.month)
        to_month = dt.datetime(from_month.year, from_month.month, end_month[1], 23, 59)

        if to_month >= end_date + relativedelta.relativedelta(months=1):  # break if we reach the end of the period
            break

