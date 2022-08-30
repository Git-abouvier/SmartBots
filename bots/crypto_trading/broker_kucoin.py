""" Recieved events orders from Portfolio and send it to the broker or exchange for execution"""
import logging

logger = logging.getLogger(__name__)

def main(send_orders_status=True):
    from smartbots.decorators import log_start_end
    from smartbots.brokerMQ import receive_events
    import datetime as dt
    from smartbots.crypto.kucoin_model import Trading
    import schedule
    from smartbots.health_handler import Health_Handler

    def check_balance() -> None:
        try:
            balance = trading.get_total_balance('USD')
            print(f'Balance {balance} {dt.datetime.utcnow()}')
            health_handler.check()
        except Exception as e:
            health_handler.send(description=e, state=0)


    def send_broker(_order: dict) -> None:
        """Send order.

        Parameters
        ----------
        order: event order
        """
        order = _order['order']
        order.exchange = 'kucoin'
        trading.send_order(order)

    # Log event health of the service
    health_handler = Health_Handler(n_check=6,
                                    name_service='broker_kucoin')
    # Create trading object
    trading = Trading(send_orders_status=send_orders_status)
    check_balance()
    # create scheduler for saving balance

    schedule.every(10).minutes.do(check_balance)
    # Launch thead for update orders status
    trading.start_update_orders_status()

    receive_events(routing_key='order', callback=send_broker)

if __name__ == '__main__':
    main()