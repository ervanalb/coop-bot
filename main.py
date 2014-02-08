import os
import threading
import time
import json
import datetime
import subprocess
import mail_handler
import re
import traceback

class CoopBot(threading.Thread):
	def __init__(self,datafile=None,emaildir=None):
		if datafile is None:
			datafile=os.path.join(os.path.dirname(__file__),'data.json')
		if not os.access(datafile, os.W_OK | os.R_OK):
			raise Exception('Cannot read/write data file "{0}"'.format(datafile))
		if emaildir is None:
			emaildir=os.path.join(os.path.dirname(__file__),'recv_email')
		if not os.path.isdir(emaildir):
			raise Exception('Email dir does not exist: "{0}"'.format(emaildir))
		self.emaildir=emaildir
		self.datafile=datafile
		self.file_lock=threading.Semaphore()
		threading.Thread.__init__(self)
		self.daemon=True
		self.init()

	# This thread handles email reception
	def run(self):
		while True:
			try:
				for f in os.listdir(self.emaildir):
					fn=os.path.join(self.emaildir,f)
					fh=open(fn,'r')
					mail=mail_handler.parse(fh)
					fh.close()
					self.receive_email(*mail)
					os.unlink(fn)
			except:
				print "Caught exception in mail reception loop:"
				traceback.print_exc()
			time.sleep(10)

	def go(self):
		self.start()
		while True:
			try:
				self.tick()
			except:
				print "Caught exception in main loop:"
				traceback.print_exc()
			time.sleep(10)

	def tick(self):
		f=self.read_file()
		if 'last_timestamp' in f:
			last_t=int(f['last_timestamp'])
		else:
			last_t=0
		if 'weeks_into_rotation' in f:
			cur_week=int(f['weeks_into_rotation'])
		else:
			cur_week=0

		t=int(time.time())
		last_dt=datetime.datetime.fromtimestamp(last_t)
		cur_dt=datetime.datetime.fromtimestamp(t)
		prev_sec=self.time_of_day_to_sec(last_dt)
		cur_sec=self.time_of_day_to_sec(cur_dt)
		if prev_sec < self.email_time <= cur_sec and cur_week==0:
			if cur_dt.weekday()==self.send_request:
				self.send_scheduling_email(f,cur_dt)
			if cur_dt.weekday()==self.send_schedule:
				if cur_week==0:
					self.send_schedule_email(f)
				cur_week=(cur_week+1)%self.rotation_length
		f['last_timestamp']=t
		f['weeks_into_rotation']=cur_week
		self.write_file(f)

	def receive_email(self,sender,subj,body):
		try:
			m=re.search(r'<(.+)>',sender)
			if m:
				sender=m.groups()[0]
			try:
				who=dict([(self.member_to_email(m).lower(),m) for m in self.get_coop_membership()])[sender.lower()]
			except KeyError:
				raise Exception('Sender {0} not found in COOP membership list.'.format(sender))

			self.receive_availability(sender,subj,body,who)
		except Exception as e:
			self.error(sender,subj,e)

	def receive_availability(self,sender,subj,body,who):
		lines=body.split('\n')
		found=False
		new_sc={}
		for line in lines:
			m=re.search('%(\d+).*:(.+)',line)
			if not m:
				continue
			found=True
			d,a=m.groups()
			d=int(d)
			a=a.strip().lower()
			if a == 'yes':
				ab=True
			elif a == 'no':
				ab=False
			else:
				raise Exception('Parse error: "{0}"'.format(line))
			if d not in new_sc:
				new_sc[d]=ab
		if not found:
			raise Exception("No availability found in email!")

		f=self.read_file()
		if 'scheduling_constraints' in f:
			sc=f['scheduling_constraints']
		else:
			sc={}
		sc[who]=new_sc
		f['scheduling_constraints']=sc
		self.write_file(f)
		body="Updated scheduling preferences successfully.\n"+repr(new_sc)
		mail_handler.send_mail(sender,subj,body)

	def error(self,sender,subj,e):
		body="I didn't understand your last email. Details:\n"+str(e)
		mail_handler.send_mail(sender,subj,body)

	def member_to_email(self,m):
		if '@' in m:
			return m
		return m+'@mit.edu'

	def mail_whole_list(self,subj,body):
		mail_handler.send_mail(self.email_list+'@mit.edu',subj,body)

	def send_scheduling_email(self,f):
		self.mail_whole_list("Update your Availability","Update your availability for the next rotation. If you don't, it will default to last rotation's.")

	def send_schedule_email(self,f,today):
		if 'scheduling_constraints' in f:
			sc=f['scheduling_constraints']
		else:
			sc={}
		members=self.get_coop_membership()
		f['scheduling_constraints']=sc
		s=self.schedule(members,sc,today)
		f['schedule']=s
		body="Schedule:\n"+self.pretty_schedule(s)
		self.mail_whole_list("This Week's Schedule",body)

	def pretty_schedule(self,schedule):
		out=""
		for day,chefs in schedule:
			dt=day.strftime("%A %b %d")
			chefs=" and ".join(chefs)
			out+="{0}: {1}\n".format(dt,chefs)
		return out

	def schedule(self,members,constraints,coop_start):
		return [(coop_start+datetime.timedelta(days=i),members[self.chefs*i:self.chefs*(i+1)]) for i in range((len(members)+self.chefs-1)/self.chefs)]

	def get_coop_membership(self):
		proc = subprocess.Popen(['blanche', self.email_list, '-noauth'], stdout=subprocess.PIPE,stderr=subprocess.PIPE)
		(out, err) = proc.communicate()
		if err:
			raise Exception(err)
		return out.rstrip().split('\n')

	def init(self):
		f=self.read_file()
		self.email_time=self.parse_time(f['email_time'])
		self.send_request=self.parse_dow(f['send_scheduling_email_on'])
		self.send_schedule=self.parse_dow(f['send_schedule_on'])
		self.rotation_length=int(f['rotation_length_in_weeks'])
		self.chefs=int(f['num_people_cooking_each_night'])
		self.email_list=f['email_list']
		self.write_file(f)

	def read_file(self):
		self.file_lock.acquire()
		f=open(self.datafile,'r')
		j=json.load(f)
		f.close()
		return j

	def write_file(self,j):
		f=open(self.datafile,'w')
		json.dump(j,f)
		f.close()
		self.file_lock.release()

	def parse_time(self,t):
		t=time.strptime(t,'%H:%M')
		return (t.tm_hour*60+t.tm_min)*60

	def time_of_day_to_sec(self,d):
		return (d.hour*60+d.minute)*60

	def parse_dow(self,d):
		return {'monday':0,'tuesday':1,'wednesday':2,'thursday':3,'friday':4,'saturday':5,'sunday':6}[d.lower()]

if __name__=='__main__':
	cb=CoopBot()
	f=cb.read_file()
	cb.send_schedule_email(f,datetime.datetime.today())
	#cb.go()
