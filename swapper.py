import common
import psmove
import time
import psutil, os
import random
import numpy
import json
from piaudio import Audio
from enum import Enum
from multiprocessing import Process, Value, Array, Queue


# How fast/slow the music can go
SLOW_MUSIC_SPEED = 1.5
#this was 0.5
FAST_MUSIC_SPEED = 0.5

# The min and max timeframe in seconds for
# the speed change to trigger, randomly selected
MIN_MUSIC_FAST_TIME = 4
MAX_MUSIC_FAST_TIME = 8
MIN_MUSIC_SLOW_TIME = 10
MAX_MUSIC_SLOW_TIME = 23

#Sensitivity of the contollers
#changes by the values in common
#TODO: make commander should be harder to kill
SLOW_MAX = 1.3
SLOW_WARNING = 0.28
FAST_MAX = 2.5
FAST_WARNING = 1.3



#How long the speed change takes
INTERVAL_CHANGE = 1.5

#How long the winning moves shall sparkle
END_GAME_PAUSE = 6
KILL_GAME_PAUSE = 4


class Opts(Enum):
    alive = 0
    selection = 1
    holding = 2
    team = 3
    is_commander = 4

class Selections(Enum):
    nothing = 0
    a_button = 1
    trigger = 2
    triangle = 3

class Holding(Enum):
    not_holding = 0
    holding = 1

class Buttons(Enum):
    middle = 524288
    all_buttons = 240
    sync = 65536
    start = 2048
    select = 256
    circle = 32
    triangle = 16
    nothing = 0

class Bool(Enum):
    no = 0
    yes = 1


#red blue
team_colors = [(255,0,0),(0,0,255)]

class Team(Enum):
    red = 1
    blue = 0


def calculate_flash_time(r,g,b, score):
    flash_percent = max(min(float(score)+0.2,1.0),0.0)
    #val_percent = (val-(flash_speed/2))/(flash_speed/2)
    new_r = int(common.lerp(255, r, flash_percent))
    new_g = int(common.lerp(255, g, flash_percent))
    new_b = int(common.lerp(255, b, flash_percent))
    return (new_r, new_g, new_b)

def track_move(move_serial, move_num, team, team_num, dead_move, force_color, music_speed, move_opts):
    #proc = psutil.Process(os.getpid())
    #proc.nice(3)

    start = False
    no_rumble = time.time() + 1
    move_last_value = None
    move = common.get_move(move_serial, move_num)
    team_colors = common.generate_colors(team_num)
    #keep on looping while move is not dead
    ready = False
    move.set_leds(0,0,0)
    move.update_leds()
    time.sleep(1)
    vibrate = False
    vibration_time = time.time() + 1
    flash_lights = True
    flash_lights_timer = 0
    change_arr = [0,0,0]

    death_time = 2
    time_of_death = time.time()
    move_opts[Opts.holding.value] = Holding.not_holding.value
    move_opts[Opts.selection.value] = Selections.nothing.value

    while True:
        if sum(force_color) != 0:
            no_rumble_time = time.time() + 5
            time.sleep(0.01)
            move.set_leds(*force_color)
            move.update_leds()
            move.set_rumble(0)
            no_rumble = time.time() + 0.5
        #if we are not dead
        elif dead_move.value == 1:
            if move.poll():

                ax, ay, az = move.get_accelerometer_frame(psmove.Frame_SecondHalf)
                total = sum([ax, ay, az])
                if move_last_value is not None:
                    change_real = abs(move_last_value - total)
                    change_arr[0] = change_arr[1]
                    change_arr[1] = change_arr[2]
                    change_arr[2] = change_real
                    change = (change_arr[0] + change_arr[1]+change_arr[2])/3

                    warning = SLOW_WARNING
                    threshold = SLOW_MAX


                    if vibrate:
                        flash_lights_timer += 1
                        if flash_lights_timer > 7:
                            flash_lights_timer = 0
                            flash_lights = not flash_lights
                        if flash_lights:
                            move.set_leds(100,100,100)
                        else:
                            move.set_leds(*team_colors[team.value])
                        if time.time() < vibration_time - 0.22:
                            move.set_rumble(110)
                        else:
                            move.set_rumble(0)
                        if time.time() > vibration_time:
                            vibrate = False
                    else:
                        move.set_leds(*team_colors[team.value])


                    if change > threshold:
                        if time.time() > no_rumble:
                            #vibrate = False
                            move.set_leds(0,0,0)
                            move.set_rumble(90)
                            dead_move.value = 0
                            time_of_death = time.time()

                    elif change > warning and not vibrate:
                        if time.time() > no_rumble:
                            vibrate = True
                            vibration_time = time.time() + 0.5
                            move.set_leds(20,50,100)
                    #else:
                    #    move.set_rumble(0)
                    

                    

                move_last_value = total
            move.update_leds()
        #if we are dead
        elif dead_move.value <= 0:
            move.set_leds(0,0,0)
            
            if time.time() - time_of_death >= death_time:
                dead_move.value = 3
        elif dead_move.value == 3:
                move_last_value = None
                dead_move.value = 1
                no_rumble = time.time() + 1
                team.value = (team.value + 1) % team_num
            

class Swapper():
    def __init__(self, moves, speed, command_queue, status_ns, audio_toggle):
        global SLOW_MAX
        global SLOW_WARNING
        global FAST_MAX
        global FAST_WARNING
        
        SLOW_MAX = common.SLOW_MAX[speed]
        SLOW_WARNING = common.SLOW_WARNING[speed]
        FAST_MAX = common.FAST_MAX[speed]
        FAST_WARNING = common.FAST_WARNING[speed]
        
        self.audio_toggle = audio_toggle
        self.move_serials = moves
        self.tracked_moves = {}
        self.dead_moves = {}
        self.teams = {}
        self.music_speed = Value('d', 1)
        self.running = True
        self.force_move_colors = {}
        self.team_num = 2

        self.start_timer = time.time()
        self.audio_cue = 0

        self.move_opts = {}

        self.command_queue = command_queue
        self.status_ns = status_ns
        self.update_time = 0


        self.generate_random_teams(self.team_num)
        if self.audio_toggle:
            music = 'audio/Joust/music/' + random.choice(os.listdir('audio/Joust/music'))

            self.start_beep = Audio('audio/Joust/sounds/start.wav')
            self.start_game = Audio('audio/Joust/sounds/start3.wav')
            self.explosion = Audio('audio/Joust/sounds/Explosion34.wav')
            fast_resample = False
            end = False
            try:
                self.audio = Audio(music, end)
            except:
                print('no audio loaded')

        #self.change_time = self.get_change_time(speed_up = True)
        self.change_time = time.time() + 8
        self.speed_up = True
        self.currently_changing = False
        self.game_end = False
        self.winning_moves = []
        self.game_loop()

    def generate_random_teams(self, team_num):
        team_pick = list(range(team_num))
        for serial in self.move_serials:
            random_choice = Value('i',  random.choice(team_pick) )
            self.teams[serial] = random_choice
            team_pick.remove(random_choice.value)
            if not team_pick:
                team_pick = list(range(team_num))

    def track_moves(self):
        for move_num, move_serial in enumerate(self.move_serials):
            time.sleep(0.02)
            dead_move = Value('i', 1)
            force_color = Array('i', [1] * 3)
            opts = Array('i', [0] * 5)
            proc = Process(target=track_move, args=(move_serial,
                                                    move_num,
                                                    self.teams[move_serial],
                                                    self.team_num,
                                                    dead_move,
                                                    force_color,
                                                    self.music_speed,

                                                    opts))
            proc.start()
            self.tracked_moves[move_serial] = proc
            self.dead_moves[move_serial] = dead_move
            self.force_move_colors[move_serial] = force_color
            self.move_opts[move_serial] = opts
            
    def change_all_move_colors(self, r, g, b):
        for color in self.force_move_colors.values():
            common.change_color(color, r, g, b)

    #need to do the count_down here
    def count_down(self):
        self.change_all_move_colors(80, 0, 0)
        if self.audio_toggle:
            self.start_beep.start_effect()
        time.sleep(0.75)
        self.change_all_move_colors(70, 100, 0)
        if self.audio_toggle:
            self.start_beep.start_effect()
        time.sleep(0.75)
        self.change_all_move_colors(0, 70, 0)
        if self.audio_toggle:
            self.start_beep.start_effect()
        time.sleep(0.75)
        self.change_all_move_colors(0, 0, 0)
        if self.audio_toggle:
            self.start_game.start_effect()

    def check_end_game(self):
        self.winning_team = -100
        team_win = True
        
        for move_serial, dead in self.dead_moves.items():
            if self.winning_team == -100:
                self.winning_team = self.teams[move_serial].value
            if self.teams[move_serial].value != self.winning_team:
                team_win = False
                #TODO: This wont work if the last move is the first of the dead_moves
                self.last_move = move_serial
            if dead.value == 0:
                #This is to play the sound effect
                dead.value = -1
                if self.audio_toggle:
                    self.explosion.start_effect()
        self.game_end = team_win


    def stop_tracking_moves(self):
        for proc in self.tracked_moves.values():
            proc.terminate()
            proc.join()
            time.sleep(0.02)

    def end_game(self):
        if self.audio_toggle:
            try:
                self.audio.stop_audio()
            except:
                print('no audio loaded to stop')
        end_time = time.time() + END_GAME_PAUSE
        h_value = 0
        self.update_status('ending',self.winning_team)
        if self.audio_toggle:
            self.end_game_sound(self.winning_team)
        while (time.time() < end_time):
            time.sleep(0.01)
            win_color = common.hsv2rgb(h_value, 1, 1)
            for win_move in self.move_serials:
                if win_move != self.last_move:
                    win_color_array = self.force_move_colors[win_move]
                    common.change_color(win_color_array, *win_color)
                else:
                    win_color_array = self.force_move_colors[win_move]
                    common.change_color(win_color_array, 1,1,1)
            h_value = (h_value + 0.01)
            if h_value >= 1:
                h_value = 0
        self.running = False

    def end_game_sound(self, winning_team):
        if winning_team == Team.red.value:
            team_win = Audio('audio/Commander/sounds/red winner.wav')
        if winning_team == Team.blue.value:
            team_win = Audio('audio/Commander/sounds/blue winner.wav')
        team_win.start_effect()

    def game_loop(self):
        self.track_moves()
        self.count_down()
        if self.audio_toggle:
            try:
                self.audio.start_audio_loop()
            except:
                print('no audio loaded to start')
        while self.running:
            #I think the loop is so fast that this causes 
            #a crash if done every loop
            if time.time() - 0.1 > self.update_time:
                self.update_time = time.time()
                self.check_command_queue()
                self.update_status('in_game')

            self.check_end_game()
            if self.game_end:
                self.end_game()

        self.stop_tracking_moves()

    def check_command_queue(self):
        package = None
        while not(self.command_queue.empty()):
            package = self.command_queue.get()
            command = package['command']
        if not(package == None):
            if command == 'killgame':
                self.kill_game()

    def kill_game(self):
        if self.audio_toggle:
            try:
                self.audio.stop_audio()
            except:
                print('no audio loaded to stop')        
        self.update_status('killed')
        all_moves = [x for x in self.dead_moves.keys()]
        end_time = time.time() + KILL_GAME_PAUSE     
        
        h_value = 0
        while (time.time() < end_time):
            time.sleep(0.01)
            color = common.hsv2rgb(h_value, 1, 1)
            for move in all_moves:
                color_array = self.force_move_colors[move]
                common.change_color(color_array, *color)
            h_value = (h_value + 0.01)
            if h_value >= 1:
                h_value = 0
        self.running = False

    def update_status(self,game_status,winning_team=-1):
        data ={'game_status' : game_status,
               'game_mode' : 'Swapper',
               'winning_team' : winning_team}
        team_total = [0,0]
        team_alive = [0,0]
        for move in self.move_serials:
            team = self.teams[move].value
            team_total[team] += 1
            if self.dead_moves[move].value == 1:
                team_alive[team] += 1
        team_comp = list(zip(team_total,team_alive))
        data['team_comp'] = team_comp
        self.status_ns.status_dict = data
                    
            
