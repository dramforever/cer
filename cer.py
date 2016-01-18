# coding=utf-8
import cherrypy
from mako.template import Template
import os
import sys
import json
import time
import threading
import config

server_path=os.path.split(sys.argv[0])[0]
def post_only():
    if cherrypy.request.method.upper()!='POST':
        cherrypy.response.headers['Allow']='POST'
        raise cherrypy.HTTPError(405)
cherrypy.tools.post=cherrypy.Tool('on_start_resource',post_only)
MAXLIVE=10
LIFESTEP=2

def auth(gnumber):
    if 'gnumber' in cherrypy.session:
        if cherrypy.session['gnumber']!=gnumber:
            del cherrypy.session['gnumber']
            if 'name' in cherrypy.session:
                del cherrypy.session['name']
            return False
        else:
            return 'name' in cherrypy.session
    return False

class Cer:
    start_lock=threading.Lock()
    playing=False
    game_number=time.time()%100000
    waiting_list={}
    players=[]
    current='N/A'
    activeNum=0
    wordCount=0

    def _start_game(self,players):
        self.players=[{'name':a,'live':MAXLIVE} for a in players]
        self.playing=True
        self.current=config.init()
        self.activeNum=0
        self.wordCount=1

    def _stop_game(self):
        self.playing=False
        self.game_number=time.time()%100000

    def _next_turn(self):
        self.activeNum=(self.activeNum+1)%len(self.players)
        while self.players[self.activeNum]['live'] is None:
            self.activeNum=(self.activeNum+1)%len(self.players)

    def _life_check(self):
        while True:
            time.sleep(.25)
            if not self.playing:
                continue
            numnow=self.activeNum
            for _ in range(int(LIFESTEP*4)):
                time.sleep(.25)
                if numnow!=self.activeNum:
                    break
            else:
                if self.players[numnow] is not None:
                    self.players[numnow]['live']-=1
                    if self.players[numnow]['live']<0:
                        self.players[numnow]['live']=None
                        if len([x for x in self.players if x['live'] is not None])<2:
                            self._stop_game()
                        else:
                            self._next_turn()

    def _refresh_waiting_list(self):
        time_limit=time.time()-3
        for name in tuple(self.waiting_list):
            if self.waiting_list[name]['time']<time_limit:
                del self.waiting_list[name]

    def _skip_turn(self,player):
        qipa='内部错误: 配置文件没有返回正确的结果'
        if self.players[player]['live']<=3:
            return '错误: 生命不足'
        result=config.skip(self.current)
        if 'valid' not in result:
            return qipa
        if result['valid']:
            if 'after' not in result:
                return qipa
            self.current=result['after']
            self.players[player]['live']-=3
            self.wordCount+=1
            self._next_turn()
            return None
        else:
            if 'reason' not in result:
                return qipa
            return '错误: %s'%result['reason']

    def __init__(self):
        t=threading.Thread(target=self._life_check,args=())
        t.setDaemon(True)
        t.start()

    @cherrypy.expose()
    def index(self):
        if self.playing:
            raise cherrypy.HTTPRedirect('/game')
        else:
            raise cherrypy.HTTPRedirect('/join')

    @cherrypy.expose()
    def join(self):
        if self.playing:
            raise cherrypy.HTTPRedirect('/game')
        cherrypy.session['gnumber']=self.game_number
        return Template(filename=os.path.join(server_path,'template/join.html'),input_encoding='utf-8')\
            .render(desc=config.description)

    @cherrypy.expose()
    @cherrypy.tools.post()
    def ping(self,status,name):
        if self.playing:
            return json.dumps({
                'error':'[start]'
            })
        if len(name)>15:
            return json.dumps({
                'error':'昵称太长'
            })
        self._refresh_waiting_list()
        if status!='idle':
            if name not in self.waiting_list:
                if len(self.waiting_list)>7:
                    return json.dumps({
                        'error':'人数已满'
                    })
                self.waiting_list[name]={'name':name,'time':time.time(),'okay':status=='okay'}
                cherrypy.session['gnumber']=self.game_number
                cherrypy.session['name']=name
            else:
                if not (auth(self.game_number) and cherrypy.session['name']==name):
                    return json.dumps({
                        'error':'昵称已经存在'
                    })
                tmp=self.waiting_list[name]
                tmp['time']=time.time()
                tmp['okay']=status=='okay'
                return json.dumps({
                    'plist':list(self.waiting_list.values())
                })
        else:
            if 'name' in cherrypy.session:
                del cherrypy.session['name']
            return json.dumps({
                'plist':list(self.waiting_list.values())
            })

    @cherrypy.expose()
    @cherrypy.tools.post()
    def start(self):
        before=[]
        with self.start_lock:
            if self.playing:
                return '[okay]'
            for a in self.waiting_list.values():
                if not a['okay']:
                    return '没有完全准备好'
                else:
                    before.append(a['name'])
            if len(before)<=1:
                return '人数不足'
            cherrypy.session.release_lock()
            time.sleep(2)
            self._refresh_waiting_list()
            if [a['name'] for a in self.waiting_list.values() if a['okay']]!=before:
                return '有人掉线'
            self._start_game(before)
            return '[okay]'

    @cherrypy.expose()
    def game(self):
        if not self.playing:
            raise cherrypy.HTTPRedirect("/join")
        auth(self.game_number) # session cleanup
        return Template(filename=os.path.join(server_path,'template/game.html'),input_encoding='utf-8')\
            .render(players=self.players,username=cherrypy.session['name'] if 'name' in cherrypy.session else None,
            MAXLIVE=MAXLIVE,desc=config.description)

    def game_status(self):
        if not self.playing:
            return json.dumps({
                'error':'[STOP]'
            })
        return json.dumps({
            'current':self.current,
            'players':self.players,
            'turn':self.players[self.activeNum]['name'],
            'count':self.wordCount,
        })

    @cherrypy.expose()
    def wait_status(self,now):
        cherrypy.session.release_lock()
        while now==self.game_status():
            time.sleep(.2)
        return self.game_status()

    @cherrypy.expose()
    @cherrypy.tools.post()
    def enter(self,word):
        if not auth(self.game_number):
            return json.dumps({
                'error':'Not Authed'
            })
        if not word:
            errcode=self._skip_turn(self.activeNum)
            if errcode:
                return json.dumps({'error':errcode})
            else:
                return json.dumps({})
        word=word.lower()
        if not self.players[self.activeNum]['name']==cherrypy.session['name']:
            return json.dumps({
                'error':'Not your turn'
            })
        msg=config.validate(self.current,word)
        if msg:
            return json.dumps({
                'error':'不被允许: %s'%msg
            })
        self.current=word
        player=self.players[self.activeNum]
        if player['live']<MAXLIVE:
            player['live']+=1
        self._next_turn()
        self.wordCount+=1
        return json.dumps({})


cherrypy.quickstart(Cer(),'/',{
    'global': {
        'engine.autoreload.on':False,
        'server.socket_host':'0.0.0.0',
        'server.socket_port':7654,
        'server.thread_pool':20,
    },
    '/': {
        'tools.sessions.on':True,
        #'tools.sessions.locking':'explicit',
    },
})
