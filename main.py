
print("Welcome to the Tick Tock Toe Server!")

import json
import uuid
import asyncio
import datetime
import random
import websockets
import string
import ssl

# Global scope #YOLO
active_games = {
}

allclients = []

# Because Python sucks
class Game:
    pass


class Client:
    STATE_ALIVE = 0
    STATE_DEAD = 1
    STATE_WINNER = 2

    def __init__(self, socket, name):
        allclients.append( self )
        self.game = None
        self.name = name
        self.uuid = str(uuid.uuid4()) # need identifier for later game process
        self.socket = socket
        self.level = 0
        self.state = self.STATE_ALIVE

    def set_game(self, game):
        print("Setting game...")
        self.game = game

    async def process(self):
        async for msg in self.socket:
            # Maybe also should have max duration or so.. not sure.
            if self.game.state == Game.GAME_STATE_FINISHED:
                print("Game finished")
                return
            print("Await..")
            await self.game.process(self, json.loads(msg))
            print("Post process...")

    def set_dead(self):
        self.state = self.STATE_DEAD

    def set_winner(self):
        self.state = self.STATE_WINNER

    # not really used
    async def heartbeat(self):
        await self.send( json.dumps({
                "type": "heartbeat"
            }) )

    async def send(self, f):
        print("Sending..")
        try:
            await self.socket.send(f)
        except websockets.exceptions.ConnectionClosedOK as a:
            print("Failed to send because client disconnected. Trying to remove client from lobby", a)
            allclients.remove( self ) # remove client from global list
            await self.game.rmv_client( self ) # remove client from game
            del self
        print("Done")

    def serialize(self):
        return {
            "name": self.name,
            "level": self.level,
            "state": self.state,
            "uuid": self.uuid
        }


class Game:
    # Has to be in sync with clients
    GAME_STATE_LOBBY = 0
    GAME_STATE_RUNNING = 1
    GAME_STATE_FINISHED = 2
    GAME_STATE_ERROR = 9998
    GAME_STATE_NONE = 9999

    def _generate_name(self): # generate game id
        return ''.join(random.choice(string.ascii_uppercase) for i in range(5))

    def __init__(self, admin_client):
        self.name = self._generate_name()
        self.admin_socket = admin_client
        self.clients = [admin_client]
        self.state = self.GAME_STATE_LOBBY
        self.isXTurn = True
        self.slots = {}

    def get_gameinfo(self):
        users = []
        for client in self.clients:
            users.append(client.serialize())

        return {
            "type": "game_info",
            "name": self.name,
            "status": self.state,
            "slots" : self.slots,
            "users": users
        }

    async def send_lines(self, lines, sender_uuid):
        for c in self.clients:
            if c.uuid == sender_uuid:
                print("Don't send lines to sender")
                continue
            await c.send(json.dumps({
                "type": "lines",
                "lines": lines
            }))

    async def send_gameinfo(self):
        for s in self.clients:
            await self.send_gameinfo_client(s)

    async def send_gameinfo_client(self, client):
        game_info = json.dumps(self.get_gameinfo())
        await client.send(game_info)

    async def send_all(self, data):
        for c in self.clients:
            # TODO: Serialized, might wanna create_task here
            await c.send(json.dumps(data))

    async def add_client(self, client):
        if self.state != self.GAME_STATE_LOBBY:
            raise ("Game not in lobby")
        self.clients.append(client)
        await self.send_gameinfo()

    async def rmv_client(self, client):
        try:
            self.clients.remove( client )
        except ValueError:
            print("Client was already missing!")
        self.state = self.GAME_STATE_LOBBY
        await self.send_gameinfo()

    async def start_game(self):
        self.state = self.GAME_STATE_RUNNING
        self.isXTurn = bool( random.randrange( 2 ) )
        for i in range( 9 ):
            self.slots[i] = False
        await self.send_all({
            "type": "start_game",
            "isxturn": self.isXTurn
        })

    async def send_move(self, pos, isxturn):
        if self.state != self.GAME_STATE_RUNNING:
            raise ("Game not running")
        await self.send_all({
            "type": "move",
            "pos": pos,
            "isxturn": isxturn
        })

    def alive_count(self):
        count = 0
        for c in self.clients:
            if c.state == Client.STATE_ALIVE:
                count += 1
        return count

    def get_last_alive(self):
        for c in self.clients:
            if c.state == Client.STATE_ALIVE:
                return c
        return None

    async def checkIfWon(self):
        lines = [
            [0, 1, 2],
            [3, 4, 5],
            [6, 7, 8],
            [0, 3, 6],
            [1, 4, 7],
            [2, 5, 8],
            [0, 4, 8],
            [2, 4, 6],
        ]
        for val in lines:
            a, b, c = val[0], val[1], val[2]
            if self.slots[a] and self.slots[a] == self.slots[b] and self.slots[a] == self.slots[c]:
                if self.slots[a] == "X": # determine winner
                    winner = self.admin_socket
                else:
                    winner = ( self.clients[1] )

                # set the game to finished
                self.state = self.GAME_STATE_FINISHED
                # inform the players
                await winner.send(json.dumps({
                    "type": "win",
                    "winner": winner.name
                }))

                # wait 5 seconds before returning to lobby
                await asyncio.sleep( 5 )
                self.state = self.GAME_STATE_LOBBY
                await self.send_gameinfo()

    def CheckIfPatt(self):
        for i in range( 9 ):
            if not self.slots[i]:
                return False
        return True


    async def process(self, client, msg):

        if msg["type"] == "start":
            # check if game state is correct
            if self.state != self.GAME_STATE_LOBBY:
                print("Error: Game already running or finished")
                return
            # check if admin
            if client != self.admin_socket:
                print("Error: Not an admin.")
                return
            print("Starting game!")
            await self.start_game()

        elif msg["type"] == "move":
            if self.state != self.GAME_STATE_RUNNING:
                print("Game is not running. Error.")
                return
            pos = int( msg["pos"] )
            print("Checking move...", pos, msg["pos"], self.isXTurn, client == self.admin_socket)
            if pos < 0 or pos > 8:
                print("Invalid move!")
                return
            if self.slots[ pos ]:
                print("Slot already set!")
                return

            if self.isXTurn and client == self.admin_socket:
                self.slots[pos] = "X"
            elif not self.isXTurn and client != self.admin_socket:
                self.slots[pos] = "O"
            else:
                print("Not your turn!")
                return

            # change turns
            self.isXTurn = not self.isXTurn
            await self.send_move( pos, self.isXTurn )
            await self.checkIfWon()

            if self.CheckIfPatt():
                self.state = self.GAME_STATE_FINISHED
                await asyncio.sleep( 5 )
                self.state = self.GAME_STATE_LOBBY
                await self.send_gameinfo()

# don't actually know if this is needed
class GameHandler:
    def __init__(self):
        pass

sockets = []

games = {}

def parse_register_msg(msg):
    j = json.loads(msg)
    if j["type"] != "register":
        print("Not a registration message")
        return None

    return j


async def newserver(websocket, path):
    # wait for registration message
    msg = parse_register_msg(await websocket.recv())
    if msg == None:
        error = {
            "type": "error",
            "msg": "Invalid registration message"
        }
        await websocket.send(json.dumps(error))
        return
    name = msg["name"]

    # creating new client
    client = Client(websocket, name)
    # send uuid (identifier) to client
    await client.send(json.dumps({
        "type": "user_info",
        "uuid": client.uuid
    }))

    # create a new game
    if (path == "/create"):
        print("Create game")
        new_game = Game(client)
        while new_game.name in games:
            new_game = Game(client)
        client.set_game(new_game)

        print("Sending gameinfo..")
        await new_game.send_gameinfo()
        print("Done")

        games[new_game.name] = new_game

        await client.process()

    # join an existing game
    elif (path.startswith("/join/")):
        game_name = path[6:]
        print("join game with id: >{}<".format( game_name ))
        if not game_name in games:
            error = {
                "type": "error",
                "msg": "Game not found."
            }
            await websocket.send(json.dumps(error))
            return

        game = games[game_name]

        if len( game.clients ) >= 2:
            error = {
                "type": "error",
                "msg": "Game is full."
            }
            await websocket.send(json.dumps(error))
            return

        client.set_game(game)
        await game.add_client(client)

        print("Sending gameinfo..")
        await game.send_gameinfo()
        await client.process()

    # idk what the client send but it was bs
    else:
        print("Unhandled path: {}".format( path ))


# not used
async def CheckAllClients():
    while True:
        print("Checking all clients....")
        await asyncio.sleep( 10 ) # check every 10 seconds
        for client in allclients:
            await client.heartbeat()

# creating ssl context for secure connection (wss instead of ws)
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
ssl_context.load_cert_chain(certfile="certificate.crt", keyfile="private.key")

# create websocket server
start_server = websockets.serve(newserver, '0.0.0.0', 5678, ping_interval=None, ssl=ssl_context)
asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().create_task(CheckAllClients())
asyncio.get_event_loop().run_forever()
