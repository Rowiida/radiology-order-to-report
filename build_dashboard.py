#!/usr/bin/env python3
"""Insert dashboard_data.json into dashboard_template.html and write dashboard.html."""
import json

template = open("dashboard_template.html").read()
data = json.load(open("dashboard_data.json"))
open("dashboard.html", "w").write(template.replace("__DATA__", json.dumps(data)))
print("wrote dashboard.html")
