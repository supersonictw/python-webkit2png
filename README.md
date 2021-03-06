# webkit2png

## About
Python script that takes screenshots (browsershots) using webkit

## Requirement
    python >= 3.7
    PyQt >= 5.13
    PyQtWebEngine >= 5.13

> Notice: Since Qt5, QtWebkit has been deprecated by QtWebEngine using Blink Engine from Chromium Project.

## Installation

### Debian/Ubuntu
- Add following packages: ``apt-get install libqt5core5a python3-pip``

#### Automated installation via ```pip```
- Install webkit2png: ```pip3 install webkit2png```

#### Manual installation via Git
- Install git: ``apt-get install git``
- Clone the project: ``git clone https://github.com/adamn/python-webkit2png.git python-webkit2png``
- Install with: ``python3 python-webkit2png/setup.py install``
- If the requirement install failed, satified with: ``pip3 install -r requirements.txt``

### FreeBSD
- install qt5 webkit: ```www/py-qt5-webkit, www/qt5-webkit, devel/py-qt5```
- install pip: ``devel/py-pip``
- install via: ``pip install webkit2png``

## Usage
- For help run: ``python3 -m webkit2png -h``

![Alt Text](http://24.media.tumblr.com/tumblr_m9trixXFHn1rxlmf0o1_400.gif)
