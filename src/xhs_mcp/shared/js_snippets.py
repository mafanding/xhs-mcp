"""JavaScript evaluated in the page context.

Every snippet is a transcription of a ``page.evaluate`` body from the
TypeScript implementation. Keeping them as JavaScript rather than rewriting the
logic in Python means the in-page semantics — including how invalid selectors
throw and how DOM quirks resolve — stay byte-for-byte identical to the original.

All snippets are arrow functions so Playwright always treats them as callables
and passes the argument through unambiguously.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# xhs_utils
# --------------------------------------------------------------------------

EXTRACT_INITIAL_STATE = """
() => {
  // Try multiple possible state objects
  const possibleStates = [
    window.__INITIAL_STATE__,
    window.__INITIAL_SSR_STATE__,
    window.__NEXT_DATA__,
    window.__NUXT__,
    window.__VUE__,
    window.__REACT_QUERY_STATE__
  ];

  for (const state of possibleStates) {
    if (state && typeof state === 'object') {
      try {
        // Use a more robust JSON serialization that handles circular references
        const seen = new WeakSet();
        return JSON.stringify(state, (key, val) => {
          if (val != null && typeof val === "object") {
            if (seen.has(val)) {
              return "[Circular]";
            }
            seen.add(val);
          }
          return val;
        });
      } catch (e) {
        continue;
      }
    }
  }

  // If no state found, try to find any global state
  const globalKeys = Object.keys(window).filter(key =>
    key.includes('STATE') || key.includes('DATA') || key.includes('INITIAL')
  );

  for (const key of globalKeys) {
    const value = window[key];
    if (value && typeof value === 'object') {
      try {
        const seen = new WeakSet();
        return JSON.stringify(value, (key, val) => {
          if (val != null && typeof val === "object") {
            if (seen.has(val)) {
              return "[Circular]";
            }
            seen.add(val);
          }
          return val;
        });
      } catch (e) {
        continue;
      }
    }
  }

  return '';
}
"""

EXTRACT_LOGIN_PROFILE = """
() => {
  const profile = {};

  // Extract user ID from URL if on profile page
  const urlMatch = window.location.href.match(/\\/user\\/profile\\/([a-f0-9]+)/);
  if (urlMatch) {
    profile.userId = urlMatch[1];
  }

  // Try to find user nickname
  const nameElement = document.querySelector(
    '.user-name, [class*="user-name"], [class*="nickname"]'
  );
  if (nameElement) {
    profile.nickname = nameElement.textContent?.trim();
  }

  // Try to find user info text that might contain stats
  const infoElement = document.querySelector('.user-info, [class*="user-info"]');
  if (infoElement) {
    const infoText = infoElement.textContent || '';
    profile.infoText = infoText;

    // Try to extract numbers from the info text (followers, following, likes)
    const numbers = infoText.match(/\\d+/g);
    if (numbers && numbers.length >= 3) {
      // Common pattern: followers, following, likes
      profile.following = parseInt(numbers[0]) || 0;
      profile.followers = parseInt(numbers[1]) || 0;
      profile.likes = parseInt(numbers[2]) || 0;
    }

    // Extract 小红书号 (XHS number)
    const xhsMatch = infoText.match(/小红书号：(\\d+)/);
    if (xhsMatch) {
      profile.xhsNumber = xhsMatch[1];
    }

    // Extract IP属地 (IP location)
    const ipMatch = infoText.match(/IP属地：([^0-9]+)/);
    if (ipMatch) {
      profile.ipLocation = ipMatch[1].trim();
    }
  }

  // Try to find avatar
  const avatarElement = document.querySelector(
    'img[class*="avatar"], img[class*="profile"], .avatar img, .profile img'
  );
  if (avatarElement) {
    profile.avatar = avatarElement.src;
  }

  return profile;
}
"""

# --------------------------------------------------------------------------
# auth_service
# --------------------------------------------------------------------------

EXTRACT_PROFILE_URL = """
() => {
  const userLinks = Array.from(document.querySelectorAll('a[href*="/user/profile/"]'));
  const currentUserLink = userLinks.find((link) => {
    const text = link.textContent?.trim();
    return (
      text === '我' ||
      (text && text.includes('profile')) ||
      (text && text.includes('用户'))
    );
  });
  return currentUserLink ? currentUserLink.href : null;
}
"""

# --------------------------------------------------------------------------
# feed_service
# --------------------------------------------------------------------------

EXTRACT_HOME_FEEDS = """
() => {
  if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.feed && window.__INITIAL_STATE__.feed.feeds && window.__INITIAL_STATE__.feed.feeds._value) {
    try {
      // Try to serialize just the feeds data to avoid circular reference issues
      const feedsData = window.__INITIAL_STATE__.feed.feeds._value;
      return JSON.stringify(feedsData);
    } catch (e) {
      return null;
    }
  }
  return null;
}
"""

EXTRACT_SEARCH_FEEDS = """
() => {
  if (window.__INITIAL_STATE__ && window.__INITIAL_STATE__.search && window.__INITIAL_STATE__.search.feeds && window.__INITIAL_STATE__.search.feeds._value) {
    try {
      // Try to serialize just the feeds data to avoid circular reference issues
      const feedsData = window.__INITIAL_STATE__.search.feeds._value;
      return JSON.stringify(feedsData);
    } catch (e) {
      return null;
    }
  }
  return null;
}
"""

# --------------------------------------------------------------------------
# Generic element helpers
# --------------------------------------------------------------------------

SCROLL_INTO_VIEW_SMOOTH = """
(el) => {
  if (el && typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}
"""

SCROLL_INTO_VIEW_INSTANT = """
(el) => {
  if (el && typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ behavior: 'instant', block: 'center' });
  }
}
"""

GET_ATTRIBUTE = "([el, name]) => el.getAttribute(name)"

GET_TAG_NAME = "(el) => el.tagName"

GET_CLASS_NAME = "(el) => el.className"

GET_TEXT_CONTENT = "(el) => el.textContent"

GET_TRIMMED_TEXT = "(el) => el.textContent?.trim()"

GET_PARENT_ELEMENT = "(el) => el.parentElement"

CLICK_ELEMENT = "(el) => { if (el) el.click(); }"

GET_BODY_TEXT = "() => document.body?.textContent || ''"

IS_INTERSECTING_VIEWPORT = """
(el) => {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return false;
  const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
  const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
  return (
    rect.bottom > 0 &&
    rect.right > 0 &&
    rect.top < viewportHeight &&
    rect.left < viewportWidth
  );
}
"""

HAS_NONZERO_BOUNDING_BOX = """
(el) => {
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}
"""

# --------------------------------------------------------------------------
# publish_base_service — submit
# --------------------------------------------------------------------------

GET_PUBLISH_BTN_ATTRS = """
(el) => ({
  isPublish: el.getAttribute('is-publish'),
  submitText: el.getAttribute('submit-text'),
  submitDisabled: el.getAttribute('submit-disabled'),
})
"""

CLOSEST_PUBLISH_PARENT = """
(el) => el.closest('[class*="publish"], [class*="btn-"]') || el.parentElement
"""

IS_CUSTOM_PUBLISH_ELEMENT = "(el) => el.tagName === 'XHS-PUBLISH-BTN'"

DISPATCH_PUBLISH_CUSTOM_EVENT = """
(el) => {
  if (!el) return;
  el.dispatchEvent(new CustomEvent('publish', { bubbles: true, composed: true }));
}
"""

DISPATCH_REACT_EVENT_CHAIN = """
(el) => {
  if (!el) return;
  const htmlEl = el;
  const rect = htmlEl.getBoundingClientRect();
  const x = rect.left + rect.width / 2;
  const y = rect.top + rect.height / 2;
  const eventInit = { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, screenX: x, screenY: y };
  const events = [
    new MouseEvent('mouseenter', eventInit),
    new MouseEvent('mouseover', eventInit),
    new MouseEvent('mousemove', eventInit),
    new MouseEvent('mousedown', { ...eventInit, button: 0, buttons: 1 }),
    new FocusEvent('focus', { bubbles: true }),
    new MouseEvent('mouseup', { ...eventInit, button: 0, buttons: 0 }),
    new MouseEvent('click', { ...eventInit, button: 0, buttons: 0 }),
  ];
  events.forEach((ev) => htmlEl.dispatchEvent(ev));
}
"""

GET_SUBMIT_BUTTON_STATE = """
(el) => {
  if (!el) return { exists: false };
  const htmlEl = el;
  const style = window.getComputedStyle(htmlEl);
  return {
    exists: true,
    disabled: htmlEl.hasAttribute('disabled') || htmlEl.getAttribute('aria-disabled') === 'true',
    pointerEvents: style.pointerEvents,
    opacity: style.opacity,
    visibility: style.visibility,
    display: style.display,
    tagName: htmlEl.tagName,
    className: htmlEl.className,
    text: htmlEl.textContent?.trim().substring(0, 20),
  };
}
"""

COLLECT_PUBLISH_DEBUG_INFO = """
() => {
  // Find all elements mentioning 发布
  const publishElements = [];
  document.querySelectorAll('*').forEach(el => {
    const text = el.textContent?.trim();
    if (text?.includes('发布')) {
      const rect = el.getBoundingClientRect();
      publishElements.push({
        tag: el.tagName,
        text: text.substring(0, 30),
        class: el.className?.substring(0, 80),
        visible: rect.width > 0 && rect.height > 0,
        rect: `${rect.width.toFixed(0)}x${rect.height.toFixed(0)} at ${rect.top.toFixed(0)},${rect.left.toFixed(0)}`,
      });
    }
  });

  return {
    url: window.location.href,
    bodyHeight: document.body.scrollHeight,
    viewportHeight: window.innerHeight,
    publishElements: publishElements.slice(0, 40),
  };
}
"""

COLLECT_COMPLETION_DEBUG_INFO = """
() => {
  const allTexts = [];
  document.querySelectorAll('div, span, p, h1, h2, h3, button').forEach((el) => {
    const text = el.textContent?.trim();
    if (text && text.length > 0 && text.length < 100) {
      allTexts.push(text);
    }
  });
  return {
    url: window.location.href,
    bodyText: document.body?.textContent?.substring(0, 500) || '',
    visibleTexts: allTexts.filter((t, i, arr) => arr.indexOf(t) === i).slice(0, 30),
  };
}
"""

EXTRACT_NOTE_ID_FROM_PAGE = """
() => {
  // Look for data attributes that might contain note ID
  const elementsWithData = document.querySelectorAll('[data-note-id], [data-id], [data-impression]');
  for (let i = 0; i < elementsWithData.length; i++) {
    const element = elementsWithData[i];
    const noteId = element.getAttribute('data-note-id') ||
      element.getAttribute('data-id') ||
      element.getAttribute('data-impression');
    if (noteId && noteId.length > 10) { // Note IDs are typically long
      return noteId;
    }
  }

  // Look for links to note pages
  const noteLinks = document.querySelectorAll('a[href*="/explore/"], a[href*="/discovery/"]');
  for (let i = 0; i < noteLinks.length; i++) {
    const link = noteLinks[i];
    const href = link.getAttribute('href');
    if (href) {
      const match = href.match(/\\/explore\\/([a-f0-9]+)/i) ||
        href.match(/\\/discovery\\/([a-f0-9]+)/i);
      if (match && match[1]) {
        return match[1];
      }
    }
  }

  // Look for any text that looks like a note ID (long hex string)
  const textContent = document.body.textContent || '';
  const noteIdPattern = /[a-f0-9]{20,}/gi;
  const matches = textContent.match(noteIdPattern);
  if (matches && matches.length > 0) {
    // Return the first long hex string found
    return matches[0];
  }

  return null;
}
"""

# --------------------------------------------------------------------------
# publish_image_service
# --------------------------------------------------------------------------

GET_UPLOAD_PAGE_STATE = """
() => {
  const bodyText = document.body?.textContent || '';
  return {
    hasImageUpload: bodyText.includes('上传图文') || bodyText.includes('拖拽图片'),
    hasVideoUpload: bodyText.includes('上传视频') || bodyText.includes('拖拽视频'),
    url: window.location.href,
  };
}
"""

DISPATCH_TAB_EVENT_CHAIN = """
(el) => {
  const htmlEl = el;
  const events = ['mouseenter', 'mouseover', 'mousedown', 'mouseup', 'click'];
  events.forEach(ev => {
    htmlEl.dispatchEvent(new MouseEvent(ev, { bubbles: true, cancelable: true }));
  });
}
"""

PREPARE_FILE_INPUT = """
(el) => {
  if (el) {
    el.setAttribute('multiple', 'multiple');
    el.removeAttribute('accept');
  }
}
"""

DISPATCH_CHANGE_EVENT = """
(el) => {
  if (el) {
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
}
"""

# --------------------------------------------------------------------------
# note_service
# --------------------------------------------------------------------------

EXTRACT_NOTES_FROM_CREATOR_CENTER = """
(selectors) => {
  const notes = [];

  // Find note elements using the creator center selector
  const noteElements = Array.from(document.querySelectorAll(selectors.NOTE_ELEMENTS));

  noteElements.forEach((element) => {
    try {
      // Extract note data from element
      const publishTime = Date.now();
      const note = {
        id: '',
        title: '',
        content: '',
        images: [],
        publishTime,
        updateTime: publishTime,
        likeCount: 0,
        commentCount: 0,
        shareCount: 0,
        collectCount: 0,
        tags: [],
        url: '',
        visibility: 'unknown',
        visibilityText: '',
      };

      // Extract note ID from data attributes or impression data
      const impressionData = element.getAttribute('data-impression');
      if (impressionData) {
        try {
          const parsed = JSON.parse(impressionData);
          const noteId = parsed?.noteTarget?.value?.noteId;
          if (noteId) {
            note.id = noteId;
            note.url = `https://www.xiaohongshu.com/explore/${noteId}`;
          }
        } catch (e) {
          // Ignore parsing errors
        }
      }

      // Extract title/content
      const titleElement = element.querySelector(selectors.TITLE_ELEMENTS);
      if (titleElement) {
        const title = titleElement.textContent?.trim() ?? '';
        note.title = title;
        note.content = title;
      }

      // Extract images - try multiple approaches for creator center
      const imageSelectors = [
        selectors.IMAGE_ELEMENTS,
        'img', // Try all img elements
        '[class*="image"]',
        '[class*="photo"]',
        '[class*="pic"]',
        '[class*="img"]',
        '[style*="background-image"]', // Background images
        'div[class*="cover"] img',
        'div[class*="thumbnail"] img',
        'div[class*="media"] img',
      ];

      let imageElements = [];
      for (const selector of imageSelectors) {
        const elements = element.querySelectorAll(selector);
        if (elements.length > 0) {
          imageElements = Array.from(elements);
          break;
        }
      }

      imageElements.forEach((img) => {
        let src = '';

        // Try different ways to get image source
        const htmlImg = img;
        if (htmlImg.src) {
          src = htmlImg.src;
        } else if (htmlImg.style && htmlImg.style.backgroundImage) {
          // Extract from background-image CSS
          const bgMatch = htmlImg.style.backgroundImage.match(/url\\(['"]?([^'"]+)['"]?\\)/);
          if (bgMatch) {
            src = bgMatch[1];
          }
        } else if (img.getAttribute('data-src')) {
          // Lazy loaded images
          src = img.getAttribute('data-src') || '';
        } else if (img.getAttribute('data-original')) {
          // Another lazy loading attribute
          src = img.getAttribute('data-original') || '';
        }

        if (
          src &&
          !src.includes('avatar') &&
          !src.includes('icon') &&
          !src.includes('logo') &&
          !src.includes('placeholder') &&
          src.startsWith('http')
        ) {
          note.images.push(src);
        }
      });

      // Extract stats - look for numbers in the element
      const allText = element.textContent || '';
      const numbers = allText.match(/\\d+/g) || [];

      // Try to extract stats from text content
      if (numbers.length >= 4) {
        // Assuming order: like, comment, share, collect, view
        note.likeCount = parseInt(numbers[0] || '0') || 0;
        note.commentCount = parseInt(numbers[1]) || 0;
        note.shareCount = parseInt(numbers[2]) || 0;
        note.collectCount = parseInt(numbers[3]) || 0;
      }

      // Extract publish time
      const timeElement = element.querySelector(selectors.PUBLISH_TIME);
      if (timeElement) {
        const timeText = timeElement.textContent?.trim() || '';
        if (timeText.includes('发布于')) {
          // Parse Chinese date format
          const dateMatch = timeText.match(
            /(\\d{4})年(\\d{1,2})月(\\d{1,2})日\\s+(\\d{1,2}):(\\d{2})/
          );
          if (dateMatch) {
            const [, year, month, day, hour, minute] = dateMatch;
            const publishDate = new Date(
              parseInt(year),
              parseInt(month) - 1,
              parseInt(day),
              parseInt(hour),
              parseInt(minute)
            );
            note.publishTime = publishDate.getTime();
            note.updateTime = publishDate.getTime();
          }
        }
      }

      // Extract visibility information
      const elementText = element.textContent?.toLowerCase() || '';
      if (elementText.includes('仅自己可见')) {
        note.visibility = 'private';
        note.visibilityText = '仅自己可见';
      } else if (elementText.includes('朋友可见')) {
        note.visibility = 'friends';
        note.visibilityText = '朋友可见';
      } else if (elementText.includes('公开')) {
        note.visibility = 'public';
        note.visibilityText = '公开';
      } else {
        // Default to public for notes without explicit visibility indicators
        note.visibility = 'public';
        note.visibilityText = '公开';
      }

      // Extract tags
      const tagElements = element.querySelectorAll(selectors.TAG_ELEMENTS);
      tagElements.forEach((tag) => {
        const tagText = tag.textContent?.trim();
        if (tagText?.startsWith('#')) {
          note.tags.push(tagText);
        }
      });

      if (note.id) {
        notes.push(note);
      }
    } catch (error) {
      // Ignore extraction errors for individual notes
    }
  });

  return notes;
}
"""

# --------------------------------------------------------------------------
# delete_service
# --------------------------------------------------------------------------

FIND_AND_CLICK_DELETE_FOR_NOTE = """
([selectors, targetNoteId]) => {
  let noteElements = [];
  for (const selector of selectors.NOTE_ITEM) {
    const elements = Array.from(document.querySelectorAll(selector));
    if (elements.length > 0) {
      noteElements = elements;
      break;
    }
  }

  if (noteElements.length === 0) {
    return { noteId: targetNoteId, title: '', found: false, error: 'No note elements found on page' };
  }

  for (const noteElement of noteElements) {
    const impressionData = noteElement.getAttribute('data-impression');
    let currentNoteId = '';

    if (impressionData) {
      try {
        const parsed = JSON.parse(impressionData);
        currentNoteId = parsed?.noteTarget?.value?.noteId || '';
      } catch {
        // Ignore parsing errors
      }
    }

    if (!currentNoteId) {
      const linkElement = noteElement.querySelector('a[href*="/explore/"], a[href*="/note/"]');
      if (linkElement) {
        const href = linkElement.getAttribute('href') || '';
        const match = href.match(/\\/explore\\/([a-zA-Z0-9]+)/);
        if (match) {
          currentNoteId = match[1];
        }
      }
    }

    if (currentNoteId === targetNoteId) {
      const titleElement = noteElement.querySelector('[class*="title"], [class*="name"]');
      const title = titleElement?.textContent?.trim() || 'Unknown';

      // Try to find a direct delete button first
      for (const selector of selectors.DELETE_BUTTON) {
        const deleteButton = noteElement.querySelector(selector);
        if (deleteButton) {
          deleteButton.click();
          return { noteId: currentNoteId, title, found: true, needsDropdown: false };
        }
      }

      // No direct delete button — check for a more-options button
      for (const selector of selectors.MORE_OPTIONS) {
        const moreButton = noteElement.querySelector(selector);
        if (moreButton) {
          moreButton.click();
          return { noteId: currentNoteId, title, found: true, needsDropdown: true };
        }
      }

      return { noteId: currentNoteId, title, found: false, error: 'Delete button not found' };
    }
  }

  return { noteId: targetNoteId, title: '', found: false, error: 'Note not found' };
}
"""

FIND_AND_CLICK_DELETE_FOR_LAST_NOTE = """
(selectors) => {
  // Try each note item selector
  let noteElements = [];
  for (const selector of selectors.NOTE_ITEM) {
    const elements = Array.from(document.querySelectorAll(selector));
    if (elements.length > 0) {
      noteElements = elements;
      break;
    }
  }

  if (noteElements.length === 0) {
    return { noteId: '', title: '', found: false, error: 'No notes found' };
  }

  // Get the first note (most recent)
  const firstNote = noteElements[0];

  // Extract note ID
  let noteId = '';
  const impressionData = firstNote.getAttribute('data-impression');

  if (impressionData) {
    try {
      const parsed = JSON.parse(impressionData);
      noteId = parsed?.noteTarget?.value?.noteId || '';
    } catch (e) {
      // Ignore parsing errors
    }
  }

  // Also try to find note ID in link
  if (!noteId) {
    const linkElement = firstNote.querySelector('a[href*="/explore/"], a[href*="/note/"]');
    if (linkElement) {
      const href = linkElement.getAttribute('href') || '';
      const match = href.match(/\\/explore\\/([a-zA-Z0-9]+)/);
      if (match) {
        noteId = match[1];
      }
    }
  }

  // Extract title
  const titleElement = firstNote.querySelector('[class*="title"], [class*="name"]');
  const title = titleElement?.textContent?.trim() || 'Unknown';

  // Try to find a direct delete button first
  for (const selector of selectors.DELETE_BUTTON) {
    const deleteButton = firstNote.querySelector(selector);
    if (deleteButton) {
      deleteButton.click();
      return { noteId, title, found: true, needsDropdown: false };
    }
  }

  // No direct delete button — check for a more-options button
  for (const selector of selectors.MORE_OPTIONS) {
    const moreButton = firstNote.querySelector(selector);
    if (moreButton) {
      moreButton.click();
      return { noteId, title, found: true, needsDropdown: true };
    }
  }

  return { noteId, title, found: false, error: 'Delete button not found' };
}
"""
