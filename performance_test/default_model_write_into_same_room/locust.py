import sys

import requests

sys.path.insert(0, '..')

import string
from datetime import datetime
from random import choice, randint

from locust import HttpUser, task, events

from test_utils.data_generator import generate_random_str

_room_id = None
_users = ['sahudy', 'eduardo', 'patricia']


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global _room_id

    print('Cleaning up...')
    response = requests.get(f'{environment.host}/clear')
    if response.status_code != 200:
        raise Exception(f'Error cleaning up: {response.status_code}')

    # Creating users
    for username in _users:
        response = requests.put(f'{environment.host}/users', json={'username': username})
        if response.status_code != 200:
            raise Exception(response.json())

    # Create room
    response = requests.put(f'{environment.host}/rooms', json={'name': 'Test room', 'members': _users})
    _room_id = response.json()['room_id']


class PutMessages(HttpUser):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.username = _users[0]

    @staticmethod
    def _generate_random_str(length: int = 32):
        return ''.join([choice(string.digits + string.ascii_letters + ' ') for __ in range(length)])

    @task
    def put_messages(self):
        self.client.put(f'/rooms/{_room_id}/messages',
                        json={'username': self.username,
                              'message': generate_random_str(randint(1, 512)),
                              'date': datetime.utcnow().isoformat()}
                        )
