""" Download historical data frrom Data Exchage and save it for use in the bot.  """
import logging
import os
import datetime as dt
from typing import List
import pandas as pd
from smartbots.database_handler import Universe
from smartbots.decorators import log_start_end
from smartbots.events import Bar
from smartbots import conf

logger = logging.getLogger(__name__)

def dataframe_to_bars(symbol:str,frame:pd.DataFrame):
    events = []
    for tuple in frame.itertuples():
        events.append(Bar(datetime=tuple.Index, ticker=symbol, open=tuple.open, high=tuple.high,
                          low=tuple.low, close=tuple.close, volume=tuple.volume))
    df = pd.DataFrame({'bar': events}, index=frame.index)
    df.index.name = 'date'
    return df

def save_test_data():
    """ Save test data for testing purposes """
    path = os.path.join(conf.path_modulo, 'crypto','data')
    # check files in folder if pkl
    files = [f for f in os.listdir(path) if f.endswith('.pkl')]
    for file in files:
        df = pd.read_pickle(os.path.join(path, file), compression='gzip')
        save_historical(file.split('.')[0], df, name_library='test_historical_1min')

def save_historical(symbol: str, data: pd.DataFrame,name_library: str= 'provider_historical_1min') -> None:
    """ Save historical in database in the library."""
    store = Universe()
    lib = store.get_library(name_library)

    # save in chunks of 1 month of data, index have to be a datetime object with name date
    data.index.name = 'date'
    data['yyyymm'] = data.index.strftime('%Y%m')
    for yyyymm in data['yyyymm'].unique():
        df = data[data['yyyymm'] == yyyymm]
        symbol_save = f'{symbol}_{yyyymm}'
        lib.write(symbol_save, df)
    print(f'Symbol {symbol} saved.')

def read_historical(symbol: str, name_library: str= 'provider_historical_1min') -> pd.DataFrame:
    """ Read historical data from initial month and end month.
        Symbols as save as :symbol_monthYear as a way to identify the data.
        """
    store = Universe()
    lib = store.get_library(name_library)

    month_list = [{l.split('_')[0]:int(l.split('_')[-1]) }    for l in lib.list_symbols()
                  if symbol in l]
    if len(month_list) > 0:
        # get from dict with less value
        symbol_min = min(month_list, key=lambda x: x.get(symbol))
        symbol_max = max(month_list, key=lambda x: x.get(symbol))
        # get key dict
        symbol_base = list(symbol_min.keys())[0]
        return {'initial':lib.read(symbol_base+'_'+str(symbol_min.get(symbol_base))).data,
                'end':lib.read(symbol_base+'_'+str(symbol_max.get(symbol_base))).data}
    return {'initial':pd.DataFrame(),'end':pd.DataFrame()}

def clean_symbol(symbols,name_library):
    store = Universe()
    lib = store.get_library(name_library)
    for symbol in symbols:
         for _s in  lib.list_symbols():
             if symbol in _s:
                lib.delete(_s)
                print(f'Symbol {_s} deleted.')

@log_start_end(log=logger)
def historical_downloader(symbols: List[str] =["BTC-USDT"], start_date: dt.datetime=dt.datetime(2022, 7, 1),
                          end_date: dt.datetime = dt.datetime.utcnow(),
                          interval: str ='1min', provider: str='kucoin', clean_symbols_database : list =[]):
    """ Main function """
    if provider == 'kucoin':
        from smartbots.crypto.kucoin_model import get_historical_data
    else:
        raise ValueError(f'Provider {provider} not implemented')
    name_library = f'{provider}_historical_{interval}'

    # check if symbols por cleaning
    if len(clean_symbols_database) > 0:
        clean_symbol(clean_symbols_database, name_library)

    # Get historical data
    for symbol in symbols:
        # Check if exist data in DB
        data_last = read_historical(symbol, name_library)
        # if exist data in DB, check if data is complete for the query period
        if len(data_last['end']) > 0 : # if exist data in DB, do smart update
            if start_date <= data_last['initial'].index.min() - dt.timedelta(days=10):
                # if not, get all data from start_date to end_date
                data_last['end'] = pd.DataFrame() # clean data_last['end'], downloading more data
            else: # start_date as last date in DB
                start_date = data_last['end'].index.max() + dt.timedelta(minutes=1)
                start_date = start_date.to_pydatetime()
        # load from provider
        _data, temporal_name = get_historical_data(symbol=symbol, interval=interval,
                                                  start_date=start_date, end_date=end_date)

        # change types to float for columns with numeric values (in this case all columns)
        for c in _data.columns:
            _data[c] = _data[c].astype(float)
        # Create bars events for saving
        data = dataframe_to_bars(symbol, _data)

        if len(data) > 0 and len(data_last['end']) > 0: #
            # update data
            data = data[data.index > data_last['end'].index.max()]
            data = pd.concat([data_last['end'], data])

        if len(data) > 0: # save data
            save_historical(symbol, data, name_library=name_library)
        # elimitante temp file
        if os.path.exists(temporal_name):
            os.remove(temporal_name)
        print(f'* Historical data for {symbol} saved')
