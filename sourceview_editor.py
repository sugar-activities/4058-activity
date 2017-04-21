# Copyright 2008 Paul Swartz
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import logging
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GObject
from gi.repository import Pango
from gi.repository import GtkSource
import os.path
import re
import mimetypes
from exceptions import ValueError, TypeError, IOError, OSError

from sugar3 import profile
from sugar3.graphics.icon import Icon

from widgets import TabLabel
import logviewer

FONT_CHANGE_STEP = 2
DEFAULT_FONT_SIZE = 10


class S_WHERE:
    selection, file, multifile = range(3)  # an enum


class GtkSourceview2Editor(Gtk.Notebook):
    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_FIRST, None, []),
        'tab-changed': (GObject.SignalFlags.RUN_FIRST, None, [str])
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        self.set_size_request(Gdk.Screen.width() / 5 * 4, -1)
        self.connect('page-removed', self._page_removed_cb)
        self.set_scrollable(True)

        self.theme_state = "light"
        self.font_size = DEFAULT_FONT_SIZE

    def set_theme(self, theme_name):
        self.theme_state = theme_name
        for i in range(0, self.get_n_pages()):
            page = self.get_nth_page(i)
            children = page.get_children()
            if isinstance(children[0], Icon):
                children[1].get_children()[0].set_theme(theme_name)
            else:
                children[0].get_children()[0].set_theme(theme_name)

    def set_font_size(self, size):
        self.font_size = size
        for i in range(0, self.get_n_pages()):
            page = self.get_nth_page(i)
            children = page.get_children()
            if isinstance(children[0], Icon):
                children[1].get_children()[0].set_font_size(size)
            else:
                children[0].get_children()[0].set_font_size(size)

    def theme_changed_cb(self, widget, theme_name):
        self.set_theme(theme_name)

    def font_changed_cb(self, widget, size):
        self.set_font_size(size)

    def get_theme(self):
        return self.theme_state

    def get_font_size(self):
        return self.font_size

    def _page_removed_cb(self, __notebook, page, n):
        try:
            page.page.remove()
        except:
            pass
            # the welcome page do not have a page property
        # Connect this only after the welcome page is removed
        # Or it causes a error since welcome page has no 'page'
        self.connect('switch-page', self._switch_page_cb)

    def _switch_page_cb(self, __notebook, page_gptr, page_num):
        self.emit('tab-changed', self._get_page(page_num).full_path)

    def set_to_page_like(self, full_path):
        for n in range(self.get_n_pages()):
            page = self._get_page(n)
            if page.full_path == full_path:
                self.set_current_page(n)
                return True
        return False

    def load_object(self, full_path, filename):
        if self.set_to_page_like(full_path):
            return
        scrollwnd = Gtk.ScrolledWindow()
        scrollwnd.set_policy(Gtk.PolicyType.AUTOMATIC,
                             Gtk.PolicyType.AUTOMATIC)

        page = GtkSourceview2Page(full_path)
        page.set_theme(self.theme_state)
        page.set_font_size(self.font_size)

        vbox = Gtk.VBox()
        if full_path.endswith('.svg'):
            icon = Icon(file=full_path, pixel_size=100,
                        xo_color=profile.get_color())
            vbox.pack_start(icon, False, False, 0)

        vbox.pack_start(scrollwnd, True, True, 0)
        scrollwnd.add(page)
        vbox.page = page
        label = filename
        page.text_buffer.connect('changed', self.__text_changed_cb)

        tablabel = TabLabel(scrollwnd, label)
        tablabel.connect(
            'tab-close',
            lambda widget, child: self.remove_page(self.page_num(child)))
        tablabel.page = page

        self.append_page(vbox, tablabel)

        self.__text_changed_cb(page.text_buffer)
        self.show_all()
        self.set_current_page(-1)

    def load_log_file(self, full_path, log_files_viewer):
        logview = logviewer.LogView(full_path, log_files_viewer)
        scrollwnd = Gtk.ScrolledWindow()
        scrollwnd.set_policy(Gtk.PolicyType.AUTOMATIC,
                             Gtk.PolicyType.AUTOMATIC)
        scrollwnd.add(logview)
        scrollwnd.page = logview
        tablabel = TabLabel(logview, os.path.basename(full_path))
        tablabel.connect(
            'tab-close', lambda widget, child:
            self.remove_page(self.page_num(child)))
        self.append_page(scrollwnd, tablabel)
        self.show_all()
        self.set_current_page(-1)

    def __text_changed_cb(self, buffer):
        if not buffer.can_undo():
            buffer.set_modified(False)
        self.emit('changed')

    def _get_page(self, order=-1):
        if order == -1:
            n = self.get_current_page()
        else:
            n = order
        if self.get_nth_page(n) is not None:
            return self.get_nth_page(n).page
        else:
            return None

    def can_undo_redo(self):
        page = self._get_page()
        if page is None:
            return (False, False)
        else:
            return page.can_undo_redo()

    def undo(self):
        page = self._get_page()
        if page:
            page.get_buffer().undo()

    def redo(self):
        page = self._get_page()
        if page:
            page.get_buffer().redo()

    def copy(self):
        page = self._get_page()
        if page:
            clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            page.get_buffer().copy_clipboard(clip)

    def paste(self):
        page = self._get_page()
        if page:
            clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            text = clip.wait_for_text()
            page.get_buffer().insert_at_cursor(text)

    def replace(self, ftext, rtext, s_opts):
        replaced = False
        if s_opts.use_regex and issubclass(type(ftext), basestring):
            ftext = re.compile(ftext)
        multifile = (s_opts.where == S_WHERE.multifile)
        if multifile and s_opts.replace_all:
            for n in range(self.get_n_pages()):
                page = self._get_page(n)
                replaced = page.page.replace(ftext, rtext, s_opts) or replaced
            return (replaced, False)  # not found-again

        page = self._get_page()
        if page:
            selection = s_opts.where == S_WHERE.selection
            replaced = page.page.replace(ftext, rtext, s_opts)
            if s_opts.replace_all:
                return (replaced, False)
            elif not selection:
                found = self.find_next(ftext, page=page)
                return (replaced, found)
            else:
                # for replace-in-selection, leave selection unmodified
                return (replaced, replaced)

    def find_next(self, ftext, page=None, direction='current'):
        if not page:
            page = self._get_page()
        if page:
            if direction == 'current' and page.set_search_text(ftext):
                return True
            elif direction:
                if page.search_next(direction):
                    return True
                else:
                    return False
            else:
                return False
        else:
            return False

    def get_all_filenames(self):
        filenames = []
        for i in range(self.get_n_pages()):
            page = self._get_page(i)
            if isinstance(page, GtkSourceview2Page):
                filenames.append(page.full_path)
        return filenames

    def save_all(self):
        logging.info('save all %i', self.get_n_pages())
        for i in range(self.get_n_pages()):
            page = self._get_page(i)
            if isinstance(page, GtkSourceview2Page):
                logging.info('%s', page.full_path)
                page.save()

    def reroot(self, olddir, newdir):
        logging.info('reroot from %s to %s' % (olddir, newdir))
        for i in range(self.get_n_pages()):
            page = self._get_page(i)
            if isinstance(page, GtkSourceview2Page):
                if page.reroot(olddir, newdir):
                    logging.info('rerooting page %s failed', page.full_path)
                else:
                    logging.info('rerooting page %s succeeded', page.full_path)

    def get_selected(self):
        return self._get_page().get_selected()

    def get_text(self):
        buff = self._get_page().text_buffer
        return buff.get_text(buff.get_start_iter(), buff.get_end_iter(),
                             False)

    def get_file_path(self):
        return self._get_page().full_path

    def close_page(self):
        return self.remove_page(self.get_current_page())

    def symbol_selected_cb(self, tree, line):
        page = self._get_page()
        _buffer = page.get_buffer()
        _iter = _buffer.get_iter_at_line(line - 1)
        _buffer.place_cursor(_iter)
        page.scroll_to_iter(_iter, 0.1, False, 0, 0)


class GtkSourceview2Page(GtkSource.View):

    def __init__(self, full_path):
        '''
        Do any initialization here.
        '''
        GtkSource.View.__init__(self)

        self.full_path = full_path

        self.set_size_request(900, 350)
        self.set_editable(True)
        self.set_cursor_visible(True)
        self.set_show_line_numbers(True)
        self.set_insert_spaces_instead_of_tabs(True)
        self.set_highlight_current_line(True)

        self.text_buffer = GtkSource.Buffer()

        stylemanager = GtkSource.StyleSchemeManager()
        self.light_theme = stylemanager.get_scheme('classic')
        self.dark_theme = stylemanager.get_scheme('oblivion')
        self.text_buffer.set_style_scheme(self.light_theme)

        # Tags for search
        tagtable = self.text_buffer.get_tag_table()
        hilite_tag = Gtk.TextTag.new('search-hilite')
        hilite_tag.props.background = '#FFFFB0'
        tagtable.add(hilite_tag)
        select_tag = Gtk.TextTag.new('search-select')
        select_tag.props.background = '#B0B0FF'
        tagtable.add(select_tag)

        self.set_buffer(self.text_buffer)

        self.set_tab_width(4)
        self.set_auto_indent(True)

        self.load_text()
        self.show()

    def set_font_size(self, size):
        desc = Pango.FontDescription(
            'Monospace %d' % size)
        # print 'Monospace %d' % size
        self.modify_font(desc)

    def set_theme(self, theme):
        if theme == "light":
            self.text_buffer.set_style_scheme(self.light_theme)
            # print "light"
        elif theme == "dark":
            self.text_buffer.set_style_scheme(self.dark_theme)
            # print "dark"

    def load_text(self, offset=None):
        '''
        Load the text, and optionally scroll to the given offset in the file.
        '''
        self.text_buffer.begin_not_undoable_action()
        _file = file(self.full_path)
        self.text_buffer.set_text(_file.read())
        _file.close()
        if offset is not None:
            self._scroll_to_offset(offset)

        self.text_buffer.set_highlight_syntax(False)
        mime_type = mimetypes.guess_type(self.full_path)[0]
        if mime_type:
            lang_manager = GtkSource.LanguageManager.get_default()
            lang_ids = lang_manager.get_language_ids()
            langs = [lang_manager.get_language(i) for i in lang_ids]
            for lang in langs:
                for m in lang.get_mime_types():
                    if m == mime_type:
                        self.text_buffer.set_language(lang)
                        self.text_buffer.set_highlight_syntax(True)
        self.text_buffer.end_not_undoable_action()
        self.text_buffer.set_modified(False)
        self.grab_focus()

    def remove(self):
        self.save()

    def save(self):
        if self.text_buffer.can_undo():  # only save if there's something to
            buff = self.text_buffer
            text = buff.get_text(buff.get_start_iter(), buff.get_end_iter(),
                                 False)
            _file = file(self.full_path, 'w')
            try:
                _file.write(text)
            except (IOError, OSError):
                pass
            _file.close()

    def can_undo_redo(self):
        '''
        Returns a two-tuple (can_undo, can_redo) with Booleans
        of those abilities.
        '''
        return (self.text_buffer.can_undo(), self.text_buffer.can_redo())

    def undo(self):
        '''
        Undo the last change in the file.  If we can't do anything, ignore.
        '''
        self.text_buffer.undo()

    def redo(self):
        '''
        Redo the last change in the file.  If we can't do anything, ignore.
        '''
        self.text_buffer.redo()

    def replace(self, ftext, rtext, s_opts):
        '''returns true if replaced (succeeded)'''
        selection = s_opts.where == S_WHERE.selection
        if s_opts.replace_all or selection:
            result = False
            if selection:
                try:
                    selstart, selend = self.text_buffer.get_selection_bounds()
                except (ValueError, TypeError):
                    return False
                offsetadd = selstart.get_offset()
                buffertext = self.text_buffer.get_slice(selstart, selend)
            else:
                offsetadd = 0
                buffertext = self.get_text()
            results = list(self._getMatches(buffertext, ftext,
                                            s_opts, offsetadd))
            if not s_opts.replace_all:
                results = [results[0]]
            else:
                results.reverse()  # replace right-to-left so that
                # unreplaced indexes remain valid.
            self.text_buffer.begin_user_action()
            for start, end, match in results:
                start = self.text_buffer.get_iter_at_offset(start)
                end = self.text_buffer.get_iter_at_offset(end)
                self.text_buffer.delete(start, end)
                self.text_buffer.insert(
                    start, self.makereplace(rtext, match, s_opts.use_regex))
                result = True
            self.text_buffer.end_user_action()
            return result
        else:  # replace, the &find part handled by caller
            try:
                start, end = self.text_buffer.get_selection_bounds()
            except TypeError:
                return False
            match = self._match(
                ftext, self.text_buffer.get_slice(start, end), s_opts)
            if match:
                self.text_buffer.delete(start, end)
                rtext = self.makereplace(rtext, match, s_opts.use_regex)
                self.text_buffer.insert(start, rtext)
                return True
            else:
                return False

    def makereplace(self, rpat, match, use_regex):
        if use_regex:
            return match.expand(rpat)
        else:
            return rpat

    def reroot(self, olddir, newdir):
        '''Returns False if it works'''
        oldpath = self.full_path
        if oldpath.startswith(olddir):
            self.full_path = os.path.join(newdir, oldpath[len(olddir):])
            return False
        else:
            return True

    def set_search_text(self, text):
        self.search_text = text

        _buffer = self.get_buffer()

        start, end = _buffer.get_bounds()
        _buffer.remove_tag_by_name('search-hilite', start, end)
        _buffer.remove_tag_by_name('search-select', start, end)

        text_iter = _buffer.get_start_iter()
        while True:
            next_found = text_iter.forward_search(
                text, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
            if next_found is None:
                break
            start, end = next_found
            _buffer.apply_tag_by_name('search-hilite', start, end)
            text_iter = end

        if self._get_next_result('current'):
            self.search_next('current')
        elif self._get_next_result('backward'):
            self.search_next('backward')

        return True

    def _get_next_result(self, direction):
        _buffer = self.get_buffer()
        if direction == 'current':
            text_iter = _buffer.get_iter_at_mark(_buffer.get_insert())
        elif direction == 'forward':
            text_iter = _buffer.get_iter_at_mark(_buffer.get_insert())
            text_iter.forward_char()
        else:
            text_iter = _buffer.get_iter_at_mark(_buffer.get_insert())

        if direction == 'backward':
            return text_iter.backward_search(
                self.search_text, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
        else:
            return text_iter.forward_search(
                self.search_text, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)

    def search_next(self, direction):
        next_found = self._get_next_result(direction)
        if next_found:
            _buffer = self.get_buffer()

            start, end = _buffer.get_bounds()
            _buffer.remove_tag_by_name('search-select', start, end)
            start, end = next_found
            _buffer.apply_tag_by_name('search-select', start, end)
            _buffer.place_cursor(start)

            self.scroll_to_iter(start, 0.1, False, 0, 0)
