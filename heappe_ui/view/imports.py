import json
from typing import Optional, Dict, Any, List
from django.http import HttpResponse, HttpRequest
from django.shortcuts import render, redirect
from django.contrib import messages
import sys
sys.path.insert(1, './py4heappe')
import heappe_v6_0_0.core as hp