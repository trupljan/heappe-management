import json
from typing import Optional, Dict, Any, List
from django.http import HttpResponse, HttpRequest
from django.shortcuts import render, redirect
from django.contrib import messages
import sys
sys.path.insert(1, '/Users/jakubkonvicka/Documents/GIT/Py4HEAppE/src')
import py4heappe.heappe_v5_1_0.core as hp