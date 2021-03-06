#
# webkit2png.py
#
# Creates screenshots of webpages using by QtWebkit.
#
# Copyright (c) 2014 Roland Tapken <roland@dau-sicher.de>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA
#
# Nice ideas "todo":
#  - Add QTcpSocket support to create a "screenshot daemon" that
#    can handle multiple requests at the same time.

import _io
import os
import time

from PyQt5 import sip
from PyQt5.QtCore import QObject, QUrl, Qt, QCoreApplication, QByteArray, QBuffer, pyqtSlot
from PyQt5.QtGui import QPalette, QImage, QColor, QPainter, QGuiApplication
from PyQt5.QtNetwork import QNetworkCookieJar, QNetworkCookie, QNetworkProxy, QNetworkAccessManager, QNetworkReply
from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEnginePage, QWebEngineView
from PyQt5.QtWidgets import QApplication, QMainWindow, QAbstractScrollArea


# Class for Website-Rendering. Uses QtWebEngine, which
# requires a running QtGui to work.


class WebkitRenderer(QObject):
    """
    A class that helps to create 'screenshots' of web pages using
    Requires PyQt5 library.
    Use "render()" to get a 'QImage' object, render_to_bytes() to get the
    resulting image as 'str' object or render_to_file() to write the image
    directly into a 'file' resource.
    """

    def __init__(self, **kwargs):
        """
        Sets default values for the properties.
        """

        # QT Initialize
        if not QApplication.instance():
            raise RuntimeError(self.__class__.__name__ +
                               " requires a running QApplication instance")
        QObject.__init__(self)

        # Initialize default properties
        self.width = kwargs.get('width', 0)
        self.height = kwargs.get('height', 0)
        self.timeout = kwargs.get('timeout', 0)
        self.wait = kwargs.get('wait', 0)
        self.scaleToWidth = kwargs.get('scaleToWidth', 0)
        self.scaleToHeight = kwargs.get('scaleToHeight', 0)
        self.scaleRatio = kwargs.get('scaleRatio', 'keep')
        self.format = kwargs.get('format', 'png')
        self.logger = kwargs.get('logger', None)

        # Set this to true if you want to capture flash.
        # Not that your desktop must be large enough for
        # fitting the whole window.
        self.grabWholeWindow = kwargs.get('grabWholeWindow', False)
        self.renderTransparentBackground = kwargs.get(
            'renderTransparentBackground', False)
        self.ignoreAlert = kwargs.get('ignoreAlert', True)
        self.ignoreConfirm = kwargs.get('ignoreConfirm', True)
        self.ignorePrompt = kwargs.get('ignorePrompt', True)
        self.interruptJavaScript = kwargs.get('interruptJavaScript', True)
        self.encodedUrl = kwargs.get('encodedUrl', False)
        self.cookies = kwargs.get('cookies', [])

        self.qWebSettings = {
            QWebEngineSettings.JavascriptEnabled: False,
            QWebEngineSettings.PluginsEnabled: False,
            QWebEngineSettings.JavascriptCanOpenWindows: False
        }

    def render(self, res):
        """
        Renders the given URL into a QImage object
        """
        # We have to use this helper object because
        # QApplication.processEvents may be called, causing
        # this method to get called while it has not returned yet.
        helper = _WebkitRendererHelper(self)
        helper.window.resize(self.width, self.height)
        image = helper.render(res)

        # Bind helper instance to this image to prevent the
        # object from being cleaned up (and with it the QWebPage, etc)
        # before the data has been used.
        image.helper = helper

        return image

    def render_to_file(self, res, file_object):
        """
        Renders the image into a File resource.
        Returns the size of the data that has been written.
        """
        assert type(file_object) is _io.BufferedRandom, "Not a file object"
        qt_format = self.format  # this may not be constant due to processEvents()
        image = self.render(res)
        q_buffer = QBuffer()
        image.save(q_buffer, qt_format)
        file_object.write(q_buffer.buffer().data())
        return q_buffer.size()

    def render_to_bytes(self, res):
        """Renders the image into an object of type 'str'"""
        qt_format = self.format  # this may not be constant due to processEvents()
        image = self.render(res)
        q_buffer = QBuffer()
        image.save(q_buffer, qt_format)
        return q_buffer.buffer().data()


# @brief The CookieJar class inherits QNetworkCookieJar to make a couple of functions public.
class CookieJar(QNetworkCookieJar):
    def __init__(self, cookies, qt_url, parent=None):
        QNetworkCookieJar.__init__(self, parent)
        for cookie in cookies:
            QNetworkCookieJar.setCookiesFromUrl(
                self, QNetworkCookie.parseCookies(QByteArray(cookie)), qt_url)

    def allCookies(self):
        return QNetworkCookieJar.allCookies(self)

    def setAllCookies(self, cookie1_list):
        QNetworkCookieJar.setAllCookies(self, cookie1_list)


class _WebkitRendererHelper(QObject):
    """
    This helper class is doing the real work. It is required to
    allow WebkitRenderer.render() to be called "asynchronously"
    (but always from Qt's GUI thread).
    """

    def __init__(self, parent):
        """
        Copies the properties from the parent (WebkitRenderer) object,
        creates the required instances of QWebPage, QWebView and QMainWindow
        and registers some Slots.
        """
        QObject.__init__(self)

        # Copy properties from parent
        for key, value in parent.__dict__.items():
            setattr(self, key, value)

        # Determine Proxy settings
        proxy = QNetworkProxy(QNetworkProxy.NoProxy)
        if 'http_proxy' in os.environ:
            proxy_url = QUrl(os.environ['http_proxy'])
            if proxy_url.scheme().startswith('http'):
                protocol = QNetworkProxy.HttpProxy
            else:
                protocol = QNetworkProxy.Socks5Proxy

            proxy = QNetworkProxy(
                protocol,
                proxy_url.host(),
                proxy_url.port(),
                proxy_url.userName(),
                proxy_url.password()
            )

        # Create and connect required PyQt5 objects
        self._page = CustomWebPage(logger=self.logger, ignore_alert=self.ignoreAlert,
                                   ignore_confirm=self.ignoreConfirm, ignore_prompt=self.ignorePrompt,
                                   interrupt_js=self.interruptJavaScript)
        self._qt_proxy = QNetworkProxy()
        self._qt_proxy.setApplicationProxy(proxy)
        self._view = QWebEngineView()
        self._view.setPage(self._page)
        self._window = QMainWindow()
        self._window.setCentralWidget(self._view)
        self._qt_network_access_manager = QNetworkAccessManager()

        # Import QWebSettings
        for key, value in self.qWebSettings.items():
            self._page.settings().setAttribute(key, value)

        # Connect required event listeners
        # assert False, "Not finish"
        self._page.loadFinished.connect(self._on_load_finished)
        self._page.loadStarted.connect(self._on_load_started)
        self._qt_network_access_manager.sslErrors.connect(self._on_ssl_errors)
        self._qt_network_access_manager.finished.connect(self._on_each_reply)

        # The way we will use this, it seems to be unnecessary to have Scrollbars enabled
        self._scroll_area = QAbstractScrollArea()
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Show this widget
        self._window.show()

    def __del__(self):
        """
        Clean up Qt5 objects.
        """
        self._window.close()
        del self._window
        del self._view
        del self._page

    def render(self, res):
        """
        The real worker. Loads the page (_load_page) and awaits
        the end of the given 'delay'. While it is waiting outstanding
        QApplication events are processed.
        After the given delay, the Window or Widget (depends
        on the value of 'grabWholeWindow' is drawn into a QScreen
        and post processed (_post_process_image).
        """
        self._load_page(res, self.width, self.height, self.timeout)
        # Wait for end of timer. In this time, process
        # other outstanding Qt events.
        if self.wait > 0:
            if self.logger:
                self.logger.debug("Waiting {} seconds ".format(self.wait))
            wait_to_time = time.time() + self.wait
            while time.time() < wait_to_time:
                if QApplication.hasPendingEvents():
                    QApplication.processEvents()

        if self.renderTransparentBackground:
            # Another possible drawing solution
            image = QImage(self._page.viewportSize(), QImage.Format_ARGB32)
            image.fill(QColor(255, 0, 0, 0).rgba())

            # http://ariya.blogspot.com/2009/04/transparent-qwebview-and-qwebpage.html
            palette = self._view.palette()
            palette.setBrush(QPalette.Base, Qt.transparent)
            self._page.setPalette(palette)
            self._view.setAttribute(Qt.WA_OpaquePaintEvent, False)

            painter = QPainter(image)
            painter.setBackgroundMode(Qt.TransparentMode)
            self._window.render(painter)
            painter.end()
        else:
            if self.grabWholeWindow:
                # Note that this does not fully ensure that the
                # window still has the focus when the screen is
                # grabbed. This might result in a race condition.
                self._view.activateWindow()
                qt_screen = QGuiApplication.primaryScreen()
                image = qt_screen.grabWindow(sip.voidptr(0))
            else:
                image = self._window.grab()

        return self._post_process_image(image)

    def _load_page(self, res, width, height, timeout):
        """
        This method implements the logic for retrieving and displaying
        the requested page.
        """

        # This is an event-based application. So we have to wait until
        # "loadFinished(bool)" raised.
        cancel_at = time.time() + timeout
        self.__loading = True
        self.__loadingResult = False  # Default

        # When "res" is of type tuple, it has two elements where the first
        # element is the HTML code to render and the second element is a string
        # setting the base URL for the interpreted HTML code.
        # When resource is of type str or unicode, it is handled as URL which
        # shall be loaded
        if type(res) == tuple:
            url = res[1]
        else:
            url = res

        if self.encodedUrl:
            qt_url = QUrl.fromEncoded(url)
        else:
            qt_url = QUrl(url)

        # Set the required cookies, if any
        self.cookieJar = CookieJar(self.cookies, qt_url)
        self._qt_network_access_manager.setCookieJar(self.cookieJar)

        # Load the page
        if type(res) == tuple:
            self._page.setHtml(res[0], qt_url)  # HTML, baseUrl
        else:
            self._page.load(qt_url)

        while self.__loading:
            if timeout > 0 and time.time() >= cancel_at:
                raise RuntimeError("Request timed out on {}".format(res))
            while QApplication.hasPendingEvents() and self.__loading:
                QCoreApplication.processEvents()

        if self.logger:
            self.logger.debug("Processing result")

        if not self.__loading_result:
            if self.logger:
                self.logger.warning("Failed to load {}".format(res))

        # Set initial viewport (the size of the "window")
        size = self._page.contentsSize()
        if self.logger:
            self.logger.debug("contentsSize: %s", size)
        if width > 0:
            size.setWidth(width)
        if height > 0:
            size.setHeight(height)

        self._window.resize(size.toSize())

    def _post_process_image(self, q_image):
        """
        If 'scaleToWidth' or 'scaleToHeight' are set to a value
        greater than zero this method will scale the image
        using the method defined in 'scaleRatio'.
        """
        if self.scaleToWidth > 0 or self.scaleToHeight > 0:
            # Scale this image
            if self.scaleRatio == 'keep':
                ratio = Qt.KeepAspectRatio
            elif self.scaleRatio in ['expand', 'crop']:
                ratio = Qt.KeepAspectRatioByExpanding
            else:  # 'ignore'
                ratio = Qt.IgnoreAspectRatio
            q_image = q_image.scaled(
                self.scaleToWidth, self.scaleToHeight, ratio, Qt.SmoothTransformation)
            if self.scaleRatio == 'crop':
                q_image = q_image.copy(
                    0, 0, self.scaleToWidth, self.scaleToHeight)
        return q_image

    @pyqtSlot(QNetworkReply, name='finished')
    def _on_each_reply(self, reply):
        """
        Logs each requested uri
        """
        self.logger.debug("Received {}".format(reply.url().toString()))

    # Event for "loadStarted()" signal
    @pyqtSlot(name='loadStarted')
    def _on_load_started(self):
        """
        Slot that sets the '__loading' property to true
        """
        if self.logger:
            self.logger.debug("loading started")
        self.__loading = True

    # Event for "loadFinished(bool)" signal
    @pyqtSlot(bool, name='loadFinished')
    def _on_load_finished(self, result):
        """
        Slot that sets the '__loading' property to false and stores
        the result code in '__loading_result'.
        """
        if self.logger:
            self.logger.debug("loading finished with result %s", result)
        self.__loading = False
        self.__loading_result = result

    # Event for "sslErrors(QNetworkReply *,const QList<QSslError>&)" signal
    @pyqtSlot('QNetworkReply*', 'QList<QSslError>', name='sslErrors')
    def _on_ssl_errors(self, reply, errors):
        """
        Slot that writes SSL warnings into the log but ignores them.
        """
        for e in errors:
            if self.logger:
                self.logger.warn("SSL: " + e.errorString())
        reply.ignoreSslErrors()

    @property
    def window(self):
        return self._window


class CustomWebPage(QWebEnginePage):
    def __init__(self, **kwargs):
        """
        Class Initializer
        """
        super().__init__()
        self.logger = kwargs.get('logger', None)
        self.ignore_alert = kwargs.get('ignore_alert', True)
        self.ignore_confirm = kwargs.get('ignore_confirm', True)
        self.ignore_prompt = kwargs.get('ignore_prompt', True)
        self.interrupt_js = kwargs.get('interrupt_js', True)

    def javaScriptAlert(self, frame, message):
        if self.logger:
            self.logger.debug('Alert: {}'.format(message))
        if not self.ignore_alert:
            return super().javaScriptAlert(frame, message)

    def javaScriptConfirm(self, frame, message):
        if self.logger:
            self.logger.debug('Confirm: {}'.format(message))
        if not self.ignore_confirm:
            return super().javaScriptConfirm(frame, message)
        else:
            return False

    def javaScriptPrompt(self, frame, message, result):
        """
        This function is called whenever a JavaScript program running inside frame tries to prompt
        the user for input. The program may provide an optional message, msg, as well as a default value
        for the input in defaultValue.
        If the prompt was cancelled by the user the implementation should return false;
        otherwise the result should be written to result and true should be returned.
        If the prompt was not cancelled by the user, the implementation should return true and
        the result string must not be null.
        """
        if self.logger:
            self.logger.debug('Prompt: {}'.format(message))
        if not self.ignore_prompt:
            return super().javaScriptPrompt(frame, message, result)
        else:
            return False

    def should_interrupt_javascript(self):
        """
        This function is called when a JavaScript program is running for a long period of time.
        If the user wanted to stop the JavaScript the implementation should return true; otherwise false.
        """
        if self.logger:
            self.logger.debug("WebKit ask to interrupt JavaScript")
        return self.interrupt_js
