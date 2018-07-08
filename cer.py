# coding=utf-8
import cherrypy
from mako.template import Template
import os
import sys
import json
import time
import threading
import base64
import socket # get self ip
import random
config=__import__('config') # cxfreeze compatible

try:
    server_path=os.path.dirname(os.path.realpath(__file__))
except NameError:
    server_path=os.getcwd()

pic_cache={fn:base64.b64encode(open(os.path.join('static/sao',fn),'rb').read()).decode() for fn in os.listdir('static/sao')}
    
def post_only():
    if cherrypy.request.method.upper()!='POST':
        cherrypy.response.headers['Allow']='POST'
        raise cherrypy.HTTPError(405)
cherrypy.tools.post=cherrypy.Tool('on_start_resource',post_only)

MAXLIVE=int(config.max_live)
assert MAXLIVE>0, 'bad config: maxlive should be positive'
LIFESTEP=int(config.life_step)
assert LIFESTEP>0, 'bad config: lifestep should be positive'
SKIPCOST=int(config.skip_cost)
assert SKIPCOST>=0, 'bad config: skipcost should not be negative'

cardinal_psw='%12d'%random.randrange(10**13)
cardinal_su_enabled=True
def yui_auth(_,u,p):
    # Disable the backdoor
    # import hashlib
 
    return cardinal_su_enabled and u=='uiharu' and p==cardinal_psw

    # hahaha='%r,%r'%(u,p)
    # for i in range(10007):
    #     hahaha=hashlib.new('sha384',hahaha.encode()).hexdigest()
    # return hahaha in [
    #     'e88226b06b7cb205fa695d8aa35622e5ea17146d921342c2c3e67f743e5d1223a2356506499dc9983356160e2414a28e',
    #     'f9dd38172aef5529caae5aa75f33aeda324679114635d5140b02125cb8079a77be3be2469a878d3333f9b36b2afe4ea7',
    #     '8ab8a311a860bf40b66e8f94fe9beb237f9b0b2d8c2ae7599f249e29016ff59d963247ee098e5d84f8506fe4bd2ae819',
    #     'a394ea24fba78184856c8294a2b9ab4b4fe19cca2031ac4e47027cf600bafff7e920aa9a3e573814dc78c178dc3bf1c3',
    #     '2f733f463f34c2aed92220988d011e29156bd533727d33d57efc7f69e10d9a59d697b2224b356a6ad208577563164587',
    # ]
    
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
    waiter_lock=threading.Lock()
    playing=False
    game_number=time.time()%100000
    waiting_list={}
    players=[]
    current='N/A'
    activeNum=0
    wordCount=0

    cardinal_paused=False
    cardinal_banip=set()
    cardinal_banname=set()
    
    def _start_game(self,players):
        self.players=[{'name':a,'live':MAXLIVE} for a in players]
        self.playing=True
        self.current=config.init()
        self.activeNum=0
        self.wordCount=1
        self.cardinal_paused=False

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
                if numnow!=self.activeNum or self.cardinal_paused:
                    break
            else:
                if self.players[numnow]['live'] is not None:
                    self.players[numnow]['live']-=1
                    if self.players[numnow]['live']<0:
                        self.players[numnow]['live']=None
                        if len([x for x in self.players if x['live'] is not None])<2:
                            self._stop_game()
                        else:
                            self._next_turn()

    def _refresh_waiting_list(self):
        time_limit=time.time()-3
        with self.waiter_lock:
            for name in tuple(self.waiting_list):
                if self.waiting_list[name]['time']<time_limit:
                    del self.waiting_list[name]

    def _skip_turn(self,player):
        qipa='内部错误: 配置文件没有返回正确的结果'
        if self.players[player]['name']!=cherrypy.session['name']:
            return '错误: 不是你的回合'
        if self.players[player]['live']<=SKIPCOST:
            return '错误: 生命不足'
        result=config.skip(self.current)
        if 'valid' not in result:
            return qipa
        if result['valid']:
            if 'after' not in result:
                return qipa
            self.current=result['after']
            self.players[player]['live']-=SKIPCOST
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
            .render(desc=config.description,pic_cache=pic_cache)

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
        if name in self.cardinal_banname or cherrypy.request.remote.ip in self.cardinal_banip:
            return json.dumps({
                'error':'您的IP或昵称被禁止'
            })
        self._refresh_waiting_list()
        if status!='idle':
            if not name:
                return json.dumps({
                    'error':'请输入昵称'
                })
            with self.waiter_lock:
                if name not in self.waiting_list:
                    if len(self.waiting_list)>=10:
                        return json.dumps({
                            'error':'人数已满'
                        })
                    self.waiting_list[name]={'name':name,'time':time.time(),'okay':status=='okay','ip':cherrypy.request.remote.ip or '???'}
                    cherrypy.session['gnumber']=self.game_number
                    cherrypy.session['name']=name
                    return json.dumps({
                        'plist':list(self.waiting_list.values())
                    })
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
                    return '有人没有准备好'
                else:
                    before.append(a['name'])
            if len(before)<=1:
                return '人数不足'
            cherrypy.session.release_lock()
            time.sleep(1.5)
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
            MAXLIVE=MAXLIVE,desc=config.description,pic_cache=pic_cache,skipcost=SKIPCOST)

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
        count=0
        cherrypy.session.release_lock()
        while now==self.game_status() and count<40:
            time.sleep(.25)
            count+=1
        return self.game_status()

    @cherrypy.expose()
    @cherrypy.tools.post()
    def enter(self,word):
        if not auth(self.game_number):
            return json.dumps({
                'error':'您没有加入游戏'
            })
        if not self.playing:
            return json.dumps({
                'error':'游戏结束'
            })
        if cherrypy.session['name'] in self.cardinal_banname or cherrypy.request.remote.ip in self.cardinal_banip:
            return json.dumps({
                'error':'您的IP或昵称被禁止'
            })
        if self.players[self.activeNum]['live'] is None:
            return json.dumps({
                'error':'你挂了'
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
                'error':'不是你的回合'
            })
        msg=config.validate(self.current,word)
        if msg:
            return json.dumps({
                'error':msg
            })
        self.current=word
        player=self.players[self.activeNum]
        if player['live']<MAXLIVE:
            player['live']+=1
        self._next_turn()
        self.wordCount+=1
        return json.dumps({})

    @cherrypy.expose()
    def cardinal(self,cmd=None):
        if cmd is None:
             return Template(filename=os.path.join(server_path,'template/cardinal.html'),input_encoding='utf-8').render()
        
        global cardinal_su_enabled
        line=cmd.split(' ')
        
        if line==['']:
            return 'Cardinal Ready'
        elif line==['game','pause']:
            self.cardinal_paused=not self.cardinal_paused
            return 'Pause Flag Set to %r'%self.cardinal_paused
        elif line==['game','stop']:
            if self.playing:
                self._stop_game()
                return 'Game Stopped'
            else:
                return 'Error: Not Playing'
        elif line==['game','start']:
            if self.playing:
                return 'Error: Already Playing'
            elif not self.waiting_list:
                return 'Error: No Players'
            else:
                self._start_game([x['name'] for x in self.waiting_list.values()])
                return 'Game Started'
        elif line[:2]==['ban','name']:
            toban=' '.join(line[2:])
            if toban in self.cardinal_banname:
                self.cardinal_banname.remove(toban)
                return 'Player Unbanned'
            else:
                self.cardinal_banname.add(toban)
                return 'Player Banned'
        elif line[:2]==['ban','ip']:
            toban=' '.join(line[2:])
            if toban in self.cardinal_banip:
                self.cardinal_banip.remove(toban)
                return 'IP Unbanned'
            else:
                self.cardinal_banip.add(toban)
                return 'IP Banned'
        elif line==['ban','clear']:
            self.cardinal_banname.clear()
            self.cardinal_banip.clear()
            return 'Ban List Cleared'
        elif line[:2]==['player','kill'] and len(line)==3:
            tokill=int(line[2])
            self.players[tokill]['live']=None
            return 'Player Killed'
        elif line[:2]==['player','heal'] and len(line)==3:
            torev=int(line[2])
            if self.players[torev]['live'] is None:
                return 'Error: Player is Dead'
            else:
                self.players[torev]['live']=MAXLIVE
                return 'Player Healed'
        elif line[:2]==['player','spawn'] and len(line)==3:
            tospawn=int(line[2])
            cherrypy.session['name']=self.players[tospawn]['name']
            return 'Target Spawned to Your Session'
        elif line[:2]==['set','count'] and len(line)==3:
            self.wordCount=int(line[2])
            return 'Count is Set'
        elif line[:2]==['set','word']:
            self.current=' '.join(line[2:])
            return 'Word is Set'
        elif line[:2]==['set','pos'] and len(line)==3:
            self.activeNum=int(line[2])
            return 'Position is Set'
        elif line==['su','on']:
            cardinal_su_enabled=True
            return 'Super User Enabled'
        elif line==['su','off']:
            cardinal_su_enabled=False
            return 'Super User Disabled'
        elif line[:1]==['eval']:
            try:
                return str(eval(' '.join(line[1:])))
            except Exception as e:
                return '%r'%e
        else:
            return 'Error: Bad Command'

print('从 config.py 加载规则: %s'%config.description)
print('Cardinal系统 用户名: uiharu 密码: %s  请公正使用'%cardinal_psw)
print('您的 IP 地址: %s'%' '.join(socket.gethostbyname_ex(socket.gethostname())[2]))
print('正在启动服务器…… 请用 7654 端口访问')
print('='*79+'\n')

conf={
    'global': {
        'engine.autoreload.on': False,
        'server.socket_host': '0.0.0.0',
        'server.socket_port': int(os.getenv('PORT')) or 7654,
        'server.thread_pool': 20,
        'tools.response_headers.on': True,
        'tools.proxy.on': True
    },
    '/': {
        'tools.sessions.on': True,
        'tools.gzip.on': True,
        #'tools.sessions.locking':'explicit',
    },
    '/static': {
        'tools.staticdir.on': True,
        'tools.staticdir.dir': os.path.join(server_path,'static'),
        'tools.staticdir.content_types': {
            'css': 'text/css',
        },
        'tools.response_headers.headers': [
            ('Cache-Control','max-age=3600'),
        ],
        'tools.sessions.on': False,
    },
    '/cardinal': {
        'tools.auth_basic.on': True,
        'tools.auth_basic.realm': 'Cardinal',
        'tools.auth_basic.checkpassword': yui_auth,
    }
}
if __name__=='__main__':
    cherrypy.quickstart(Cer(),'/',conf)
else:
    wsgi_app=cherrypy.Application(Cer(),'/',conf)
