#!/usr/bin/env  python

__license__   = 'GPL v3'
__copyright__ = '2009, Darko Miletic <darko.miletic at gmail.com>'
'''
www.hln.be
'''
from calibre.web.feeds.news import BasicNewsRecipe
from calibre.ebooks.BeautifulSoup import Tag

class HLN_be(BasicNewsRecipe):
    title                 = 'Het Belang Van Limburg'
    __author__            = 'Darko Miletic'
    description           = 'News from Belgium in Dutch'
    publisher             = 'Het Belang Van Limburg'
    category              = 'news, politics, Belgium'
    oldest_article        = 2
    max_articles_per_feed = 100
    no_stylesheets        = True
    use_embedded_content  = False
    encoding              = 'utf-8'
    language              = _('Dutch')
    lang                  = 'nl-BE'
    direction             = 'ltr'

    html2lrf_options = [
                          '--comment'  , description
                        , '--category' , category
                        , '--publisher', publisher
                        ]

    html2epub_options = 'publisher="' + publisher + '"\ncomments="' + description + '"\ntags="' + category + '"\noverride_css=" p {text-indent: 0cm; margin-top: 0em; margin-bottom: 0.5em} "'

    keep_only_tags = [dict(name='div', attrs={'class':'art_box2'})]
    remove_tags    = [
                         dict(name=['embed','object'])
                     ]

    feeds = [(u'Alle nieuws', u'http://www.hln.be/rss.xml')]

    def preprocess_html(self, soup):
        del soup.body['onload']
        for item in soup.findAll(style=True):
            del item['style']
        soup.html['lang']     = self.lang
        soup.html['dir' ]     = self.direction
        mlang = Tag(soup,'meta',[("http-equiv","Content-Language"),("content",self.lang)])
        mcharset = Tag(soup,'meta',[("http-equiv","Content-Type"),("content","text/html; charset=utf-8")])
        soup.head.insert(0,mlang)
        soup.head.insert(1,mcharset)
        return soup

