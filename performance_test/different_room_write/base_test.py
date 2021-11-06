import json
from multiprocessing import Queue
from queue import Empty
from threading import Thread

import requests
from locust.runners import MasterRunner, WorkerRunner

import string
from datetime import datetime
from random import choice


class UserLoad(Thread):

    def __init__(self, queue: Queue):
        super().__init__()
        self._queue = queue
        self.exception_happened = False

    def run(self) -> None:
        while True:
            try:
                route, user_ = self._queue.get(timeout=1)
                print(route, user_)
                response = requests.put(route, json={'username': user_})
                if response.status_code != 200:
                    self.exception_happened = True
                    raise Exception(response.json())
            except Empty:
                break


class RoomLoad(Thread):

    def __init__(self, queue: Queue):
        super().__init__()
        self._queue = queue
        self.exception_happened = False
        self.user_room_per_amount = {}

    def run(self) -> None:
        while True:
            try:
                route, name_, users_ = self._queue.get(timeout=1)
                print(route, name_, users_)
                response = requests.put(route, json={'name': name_, 'members': users_})
                if response.status_code != 200:
                    self.exception_happened = True
                    raise Exception(response.json())
                room_id = response.json()['room_id']
                amount_in_room = str(len(users_))
                if amount_in_room not in self.user_room_per_amount:
                    self.user_room_per_amount[amount_in_room] = {}
                for user in users_:
                    if user not in self.user_room_per_amount[amount_in_room]:
                        self.user_room_per_amount[amount_in_room][user] = []
                    self.user_room_per_amount[amount_in_room][user].append(room_id)
            except Empty:
                break


def _perform_load(queue_: Queue, worker_class, worker_amount: int = 30):
    workers = []
    for __ in range(worker_amount):
        worker = worker_class(queue_)
        worker.start()
        workers.append(worker)
    for worker in workers:
        worker.join()
        if worker.exception_happened:
            raise Exception('Error loading!')
    return workers

def _setup_test(
        environment, create_indices: bool, message_base_route: str, write_concern_majority: bool
):
    user_room_per_amount = {}
    print(f'Cleaning up for tests in {message_base_route}...')
    response = requests.get(f'{environment.host}/clear')
    if response.status_code != 200:
        raise Exception(f'Error cleaning up: {response.status_code}')
    if create_indices:
        print('Creating indices...')
        response = requests.post(f'{environment.host}/{message_base_route}/indices')
        if response.status_code != 200:
            raise Exception(f'Error creating indices: {response.status_code}')
    if write_concern_majority:
        print('Checking write_concern majority...')
        response = requests.get(f'{environment.host}/write_concern')
        if response.status_code != 200 or response.json()['write_concern'] != 'majority':
            raise Exception(f'Please set the WRITE_CONCERN env var as majority before starting the app')

    # Creating users
    queue = Queue()
    with open('/mnt/locust/users.txt') as f:
        for line in f.readlines():
            username = line.strip()
            if username:
                queue.put((f'{environment.host}/users', username))
    _perform_load(queue_=queue, worker_class=UserLoad)
    print('Created users')

    # Create room
    queue = Queue()
    with open('/mnt/locust/rooms.txt') as f:
        i = 0
        for line in f.readlines():
            if line.strip():
                users = [u.strip() for u in line.split(',')]
                queue.put((f'{environment.host}/rooms', f'Test room {i}', users))
                i += 1

    workers = _perform_load(queue_=queue, worker_class=RoomLoad)
    print('Created rooms')

    for worker in workers:
        for amount, values in worker.user_room_per_amount.items():
            if amount not in user_room_per_amount:
                user_room_per_amount[amount] = dict(values)
            else:
                for user in values:
                    if user not in user_room_per_amount[amount]:
                        user_room_per_amount[amount][user] = list(values[user])
                    else:
                        user_room_per_amount[amount][user].extend(values[user])
    return user_room_per_amount


def _send_user_room_per_amount(environment, user_room_per_amount: dict):
    environment.runner.send_message('receive_user_room_per_amount', json.dumps(user_room_per_amount))


def _receive_user_room_per_amount(msg):
    return json.loads(msg.data)


def _on_locust_init(environment, send_user_room_per_amount_func, receive_user_room_per_amount_func):
    if not isinstance(environment.runner, WorkerRunner):
        environment.runner.register_message('send_user_room_per_amount', send_user_room_per_amount_func)
    if not isinstance(environment.runner, MasterRunner):
        environment.runner.register_message('receive_user_room_per_amount', receive_user_room_per_amount_func)


class BasePutMessages:

    def __init__(self, user_room_per_amount: dict, messages_route: str, client):
        self._user_room_per_amount = user_room_per_amount
        self._messages_route = messages_route
        self.client = client

    @staticmethod
    def _generate_random_str(length: int = 32):
        return ''.join([choice(string.digits + string.ascii_letters + ' ') for __ in range(length)])

    def put_messages(self, message_len: int, amount_per_room: int):
        amount_per_room_str = str(amount_per_room)
        username = choice(list(self._user_room_per_amount[amount_per_room_str].keys()))
        room_id = choice(self._user_room_per_amount[amount_per_room_str][username])
        self.client.put(f'/rooms/{room_id}/{self._messages_route}',
                        json={'username': username,
                              'message': f'{self._generate_random_str(message_len)}',
                              'date': datetime.utcnow().isoformat()},
                        name=f'/{self._messages_route}')
