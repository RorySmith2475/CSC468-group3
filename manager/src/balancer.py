from worker import UserIds
from parser import Command, parse_command
from threading import Thread, Timer
import time
import os
import pika
import queue
import sys
import random

class Balancer():
    def __init__(self, workers, queue, mutex):
        self.workers = workers
        self.user_ids = []
        self.command_queue = queue
        self.mutex = mutex

        self._cleanup_timer = None
        self._total_commands_seen = 0
        self._CLEANUP_PERIOD = 20.0 # Seconds
        self._USER_TIMEOUT = 40.0 # Seconds

        self._send_address = "rabbitmq-backend"
        self._exchange = os.environ["BACKEND_EXCHANGE"]
        self._connection = None
        self._channel = None

    def setup(self):
        while True:
            print("Attempting to connect to rabbitmq-backend")
            try:
                self._connection = pika.BlockingConnection(
                    pika.ConnectionParameters(
                        host=self._send_address,
                        heartbeat=600,
                        blocked_connection_timeout=300)
                )
                self._channel = self._connection.channel()
                self._channel.exchange_declare(exchange=self._exchange)
                self._channel.confirm_delivery()

                print("Connected to rabbitmq-backend")
                return

            except pika.exceptions.AMQPChannelError as err:
                print(f"Failed to connect to rabbitmq-backend with error {err}")
                time.sleep(2)
            except pika.exceptions.AMQPConnectionError:
                print("Failed to connect to rabbitmq-backend")
                time.sleep(2)

    ''' Connects to frontend and backend rabbit queue
    and then begins listening for incoming commands. 
    '''
    def run(self):
        self.setup()
        self._cleanup_timer = Timer(
            self._CLEANUP_PERIOD,
            self.cleanup,
            args=None,
            kwargs=None
        )
        self._cleanup_timer.start()

    def balance(self, message: str):
        self._total_commands_seen = self._total_commands_seen + 1
        routing_key = None
        command = parse_command(message)

        if command.command == "DUMPLOG":
            while not self.all_workers_finished():
                print("Waiting for all work to be finished before DUMPLOG can be performed...")
                time.sleep(5)
            routing_key = "worker_queue_0"
            print("Sent DUMPLOG to worker_queue_0")
        else:
            with self.mutex:
                for user in self.user_ids:
                    if user.user_id == command.uid:
                        for worker in self.workers:
                            if worker.container_id == user.assigned_worker:
                                routing_key = worker.route_key
                                worker.commands.append(command.number)
                                break

                        user.last_seen = time.time()
                        break

                if routing_key is None:
                    routing_key = self.assign_worker(command.uid, command.number)

        self.publish(message, routing_key)

    def publish(self, message: str, routing_key: str):
        try:
            self._channel.basic_publish(
                exchange=self._exchange,
                routing_key=routing_key,
                body=message,
                properties=pika.BasicProperties(delivery_mode=1),
                mandatory=True
            )
        except:
            self.setup()
            self.publish(message, routing_key)
    
    ''' Assigns a uid to a worker. Returns the routing key for the assigned worker'''
    def assign_worker(self, uid: str, number: int) -> str:
        # Get list of workers with min number of users assigned to them
        min_workers = [self.workers[0]]
        minimum = len(self.workers[0].commands)
        num_per_worker = self.users_per_worker()
        for worker in self.workers:
            if (length := num_per_worker.get(worker.container_id, 10000)) <= minimum:
                if minimum == length:
                    min_workers.append(worker)
                else:
                    minimum = length
                    min_workers = [worker]

        # Get worker with least amount of active commands from min_workers
        minimum = len(min_workers[0].commands)
        best_workers = [min_workers[0]]
        for worker in min_workers:
            if (length := len(worker.commands)) <= minimum:
                if minimum == length:
                    best_workers.append(worker)
                else:
                    minimum = length
                    best_workers = [worker]

        best_worker = random.choice(best_workers)

        # for user in self.user_ids:
        #     if user.user_id == uid:
        #         user.last_seen = time.time()
        #         user.assigned_worker = best_worker.container_id
        #         best_worker.commands.append(number)
        #         return best_worker.route_key

        print(f"Assigned worker {best_worker.container_id} to {uid}")
        self.user_ids.append(UserIds(
            user_id=uid,
            assigned_worker=best_worker.container_id,
            last_seen=time.time()
        ))

        best_worker.commands.append(number)
        return best_worker.route_key

    ''' Removes users from user_ids list if they havent been seen for USER_TIMEOUT.
    Also prints current activity for all workers and users.
    '''
    def cleanup(self):
        with self.mutex:
            total_length = 0
            for worker in self.workers:
                worker_len = len(worker.commands)
                total_length = total_length + worker_len
                if worker_len > 0:
                    print(worker)
            if total_length > 0:
                print(f"Total active commands: {total_length}")
            print(f"Total commands seen: {self._total_commands_seen}")
            print(f"Total active users: {len(self.user_ids)}")

            self.user_ids = [user for user in self.user_ids if (time.time() - user.last_seen < self._USER_TIMEOUT)]

        sys.stdout.flush()

        self._cleanup_timer = Timer(
            self._CLEANUP_PERIOD,
            self.cleanup,
            args=None,
            kwargs=None
        )
        self._cleanup_timer.start()

    def all_workers_finished(self) -> bool:
        with self.mutex:
            for worker in self.workers:
                for _ in worker.commands:
                    return False

        return True

    def users_per_worker(self) -> dict:
        num_per_worker = {}
        for user in self.user_ids:
            num_per_worker.update({
                user.assigned_worker: num_per_worker.get(user.assigned_worker, 0) + 1
            })
        
            for worker in self.workers:
                num_per_worker.update({
                    worker.container_id: num_per_worker.get(worker.container_id, 0)
                })

        return num_per_worker
