import email
import encodings
#import json
#import os
#import quopri
import re
#import requests
#import sys

def parse(f):
	msg = email.message_from_file(f)
	sender = msg["From"]
	subject = msg["Subject"]

	for part in msg.walk():
		if part.is_multipart():
			continue
		if part.get_content_type() == "text/plain":
			aliases = encodings.aliases.aliases.keys()
			css=filter(lambda x: x in aliases, part.get_charsets())
			msg=part.get_payload(decode=True)
			msg=re.sub(r'\r\n','\n',msg) # fuck you windows
			msg=strip_reply(msg)
			body=msg
			break

	return sender,subject,body

def strip_reply(msgtxt):
	delims = (
		#r"-- ?\n",
		r"-----Original Message-----",
		r"________________________________",
		r"\nOn [\s\S]+?wrote:\n",
		#r"Sent from my iPhone",
		#r"sent from my BlackBerry",
		#r"\n>"
		)
	for dlm in delims:
		msgtxt = re.split(dlm, msgtxt, 1)[0]
	return msgtxt

def send_mail(to,subj,body):
	print to,subj
	print body
	return
