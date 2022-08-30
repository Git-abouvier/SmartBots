import importlib
from dataclasses import dataclass
from smartbots.brokerMQ import Emit_Events, receive_events
from smartbots.engine import data_reader
import datetime as dt
import pandas as pd
from smartbots.database_handler import Universe
from smartbots import conf
from smartbots.health_handler import Health_Handler

class Portfolio_Constructor(object):
    def __init__(self, conf_portfolio: dict, run_real: bool = False, asset_type: str = None,
                 send_orders_to_broker: bool = False, start_date: dt.datetime =dt.datetime(2022,1,1)
                 , end_date: dt.datetime = dt.datetime.utcnow()):
        """ Run portfolio of strategies"""
        self.print_events_realtime = False
        self.in_real_time = False
        self.start_date = start_date
        self.end_date = end_date
        if asset_type is None:
            error_msg = 'asset_type is required'
            raise ValueError(error_msg)
        self.conf_portfolio = conf_portfolio
        self.name = conf_portfolio['Name']
        self.data_sources = conf_portfolio['Data_Sources']
        self.run_real = run_real
        self.asset_type = asset_type
        self.ticker_to_strategies = {}  # fill with function load_strategies_conf()
        self._load_strategies_conf()
        self.send_orders_to_broker = send_orders_to_broker
        self.orders = []
        self.bets = []
        # health log
        self.health_handler = Health_Handler(n_check=10,
                                             name_service=self.name)
        if self.send_orders_to_broker:
            self.emit_orders = Emit_Events()

    def _load_strategies_conf(self):
        """ Load the strategies configuration """
        list_stra = {}
        for parameters in self.conf_portfolio['Strategies']:
            strategy_name = parameters['strategy']
            _id = parameters['id']
            ticker = parameters['params']['ticker']
            set_basic = False
            if strategy_name == 'Basic_Strategy':
                set_basic = True
            if strategy_name not in list_stra:  # import strategy only once
                list_stra[strategy_name] = self._get_strategy(self.asset_type, strategy_name)
            if ticker not in self.ticker_to_strategies:
                self.ticker_to_strategies[ticker] = []
            strategy_obj = list_stra[strategy_name](parameters['params'], id_strategy=_id,
                                                    callback=self._callback_orders, set_basic = set_basic)
            self.ticker_to_strategies[ticker].append(strategy_obj)

    def _get_strategy(self, asset_type: str, strategy_name: str):
        """ Load the strategy dinamically"""
        try:
            name = f'smartbots.{asset_type}.strategies.{strategy_name.lower()}'
            strategy_module = importlib.import_module(name)
            strategy_class = getattr(strategy_module, strategy_name)
            return strategy_class
        except Exception as e:
            raise ValueError(f'Error loading strategy {strategy_name}') from e

    def get_saved_values_strategy(self, id_strategy: int = None):
        # Get saved values for the strategy
        frames = {}
        for t in self.ticker_to_strategies.keys():
            for strategy in self.ticker_to_strategies[t]:
                if id_strategy is None or strategy.id_strategy == id_strategy:
                    df = pd.DataFrame(strategy.get_saved_values())
                    df['ticker'] = t
                    df.set_index('datetime', inplace=True)
                    frames[strategy.id_strategy] = df
        return frames

    def get_saved_values_strategies_last(self):
        # Get last saved values for the strategy
        dict_values = {}
        for t in self.ticker_to_strategies.keys():
            for strategy in self.ticker_to_strategies[t]:
                values = strategy.get_saved_values()
                dict_values[strategy.id_strategy] = {}
                dict_values[strategy.id_strategy]['ticker'] = strategy.ticker
                dict_values[strategy.id_strategy]['close'] = values['close'][-1]
                dict_values[strategy.id_strategy]['position'] = values['position'][-1]
                dict_values[strategy.id_strategy]['quantity'] = strategy.quantity

        return dict_values

    def run(self):
        print(f'running Portfolio {self.name}')
        self.run_simulation()
        if self.run_real:
            self.run_realtime()

    def run_simulation(self):
        """ Run Backtest portfolio"""
        self.in_real_time = False
        if self.asset_type == 'crypto':
            for event in data_reader.load_tickers_and_create_events(self.data_sources,
                                                                    start_date=self.start_date, end_date=self.end_date):
                self._callback_datafeed(event)
        elif self.asset_type == 'betting':
            for event in data_reader.load_tickers_and_create_events_betting(self.data_sources):
                self._callback_datafeed_betting(event)
        else:
            raise ValueError(f'Asset type {self.asset_type} not supported')

    def process_petitions(self, event_info: dict):
        """ Recieve a event peticion and get the data from the data source and save it in the DataBase"""
        if 'petition' in event_info:
            data_to_save = None
            print(f'Petition {event_info["petition"]}')
            petition = event_info['petition']
            if petition.function_to_run == 'get_saved_values_strategy':
                data_to_save = self.get_saved_values_strategy()
            elif petition.function_to_run == 'get_saved_values_strategies_last':
                data_to_save = self.get_saved_values_strategies_last()
            if data_to_save is not None:
                name_library = petition.path_to_saving
                name = petition.name_to_saving
                store = Universe()
                lib = store.get_library(name_library)
                lib.write(name, data_to_save)
                print(f'Save {name} in {name_library}.')


    def run_realtime(self):
        self.print_events_realtime = True
        self.in_real_time = True
        print('running real  of the Portfolio, waitig Events')
        if self.asset_type == 'crypto':
            receive_events(routing_key='bar,petition', callback=self._callback_datafeed)
        elif self.asset_type == 'betting':
            receive_events(routing_key='odds,petition', callback=self._callback_datafeed_betting)
        else:
            raise ValueError(f'Asset type {self.asset_type} not supported')

    def _callback_orders(self, order_or_bet: dataclass):
        """ Order event from strategies"""
        order_or_bet.portfolio_name = self.name
        order_or_bet.status = 'from_strategy'
        if self.asset_type == 'crypto':
            self.orders.append(order_or_bet)
            if self.in_real_time and self.send_orders_to_broker:
                print(order_or_bet)
                self.emit_orders.publish_event('order', order_or_bet)

        elif self.send_orders_to_broker and self.asset_type == 'betting':
            self.bets.append(order_or_bet)
            if self.in_real_time:
                print(order_or_bet)
                self.emit_orders.publish_event('bet', order_or_bet)
        elif self.send_orders_to_broker:
            raise ValueError(f'Asset type {self.asset_type} not supported')

    def _callback_datafeed_betting(self, event_info: dict):
        """ Feed portfolio with data from events for asset type Betting,
         recieve dict with key as topic and value as event"""
        if self.in_real_time:
            self.health_handler.check()
        if 'odds' in event_info:
            odds = event_info['odds']
            if self.print_events_realtime:
                print(odds)
            try:
                strategies = self.ticker_to_strategies[odds.ticker]
            except:
                self.ticker_to_strategies[odds.ticker] = []  # default empty list
                strategies = self.ticker_to_strategies[odds.ticker]

            for strategy in strategies:
                strategy.add_odds(odds)

    def _callback_datafeed(self, event_info: dict):
        """ Feed portfolio with data from events for asset Crypto and Finance,
        recieve dict with key as topic and value as event"""
        if self.in_real_time:
            self.health_handler.check()
        if 'bar' in event_info:
            bar = event_info['bar']
            if self.print_events_realtime:
                print(bar)
            try:
                strategies = self.ticker_to_strategies[bar.ticker]
            except:
                self.ticker_to_strategies[bar.ticker] = []  # default empty list
                strategies = self.ticker_to_strategies[bar.ticker]
            for strategy in strategies:
                strategy.add_event('bar', bar)
        elif 'petition' in event_info:
            """ If the petition do not work it keeps working"""
            try:
                self.process_petitions(event_info)
            except Exception as e:
                print(f'Error processing petitions {e}')

