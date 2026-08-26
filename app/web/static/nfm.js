// ========== Configuration ==========
const STORAGE_PREFIX = 'focusNews_';
const VISITED_LINKS_KEY = 'visitedLinks';
const SECTION_VISIBILITY_KEY = 'sectionVisibilityState';
const THEME_KEY = 'theme';
const HIDE_UNINTERESTING_KEY = 'hideUninteresting';

// Section visibility state: 0 = both, 1 = sources only, 2 = topics only
let sectionVisibilityState = parseInt(localStorage.getItem(SECTION_VISIBILITY_KEY) || '0');

// Currently active filter value (null = no filter)
let currentFilterValue = null;

// Currently active live-search term ('' = no search active)
let currentSearchTerm = '';

// ========== Theme Management ==========
function initTheme() {
  const savedTheme = localStorage.getItem(THEME_KEY);
  if (savedTheme) {
    document.documentElement.setAttribute('data-theme', savedTheme);
  }
  // If no saved theme, use default (day mode, no data-theme attribute)
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const newTheme = current === 'dark' ? null : 'dark';
  
  if (newTheme) {
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem(THEME_KEY, newTheme);
  } else {
    document.documentElement.removeAttribute('data-theme');
    localStorage.removeItem(THEME_KEY);
  }
}

// ========== Click Tracking ==========
// async function trackClick(event, lid, rating) {
//   event.preventDefault();
//   try {
//     const uid = getUidFromPath();
//     await fetch(`${window.location.pathname}/clicktrack?lid=${lid}&rating=${rating}`, {
//       method: 'GET',
//     });
//   } catch (error) {
//     console.error('Error tracking click:', error);
//   }
// }

async function trackClickFollow(event, link, lid, rating) {
  event.preventDefault();
  const href = link.href;
  try {
    const uid = getUidFromPath();
    await fetch(`${window.location.pathname}/clicktrack?lid=${lid}&rating=${rating}`, {
      method: 'GET',
    });
    window.location.href = href;
  } catch (error) {
    console.error('Error tracking click:', error);
    window.location.href = href;
  }
}

async function clickFollow(event, link) {
  event.preventDefault();
  window.location.href = link.href;
}

function getUidFromPath() {
  const pathParts = window.location.pathname.split('/');
  return pathParts[pathParts.length - 1];
}

// ========== Hide Uninteresting Items ==========
async function hideUninterestingItems(event, sectionName, sectionType, buttonElement) {
  event.preventDefault();
  
  // Disable button to prevent double-clicks
  buttonElement.disabled = true;
  const originalText = buttonElement.textContent;
  buttonElement.textContent = 'Verarbeite...';
  
  try {
    // Find the parent details element
    const detailsElement = buttonElement.closest('details');
    if (!detailsElement) {
      console.error('Could not find parent details element');
      return;
    }
    
    // Get the visited links manager to check which items have been clicked
    const visitedLinksManager = window.visitedLinksManagerInstance || new VisitedLinksManager();
    
    // Collect all unvisited (uninteresting) link IDs and URLs from this section
    const uninterestingLids = [];
    const uninterestingUrls = new Set();
    
    // Get all news items (main items, not duplicates)
    const newsItems = detailsElement.querySelectorAll('.news-item:not(.news-item-dub)');
    
    newsItems.forEach(item => {
      const link = item.querySelector('a.news-title');
      if (link && !visitedLinksManager.isVisited(link.href)) {
        // Extract lid from the onclick attribute
        const onclickAttr = link.getAttribute('onclick');
        const lidMatch = onclickAttr ? onclickAttr.match(/'([^']+)'/) : null;
        if (lidMatch && lidMatch[1]) {
          uninterestingLids.push(lidMatch[1]);
          uninterestingUrls.add(link.href);
        }
      }
      
      // Also collect unvisited duplicates within this item
      const duplicates = item.querySelectorAll('.news-item-dub a.news-title-dub');
      duplicates.forEach(dupLink => {
        if (!visitedLinksManager.isVisited(dupLink.href)) {
          uninterestingUrls.add(dupLink.href);
        }
      });
    });
    
    if (uninterestingLids.length === 0) {
      buttonElement.textContent = 'Nichts auszublenden';
      setTimeout(() => {
        buttonElement.textContent = originalText;
        buttonElement.disabled = false;
      }, 2000);
      return;
    }
    
    // Send the uninteresting items to the backend (as negative samples)
    const uid = getUidFromPath();
    const response = await fetch(`${window.location.pathname}/save_negative_samples`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        lids: uninterestingLids,
        section_name: sectionName,
        section_type: sectionType
      }),
    });
    
    if (response.ok) {
      const result = await response.json();
      buttonElement.textContent = `🗑️ ${result.count} ausgeblendet`;
      
      // Hide all items with these URLs globally (across all sections)
      document.querySelectorAll('.news-item:not(.news-item-dub)').forEach(item => {
        const link = item.querySelector('a.news-title');
        if (link && uninterestingUrls.has(link.href)) {
          item.style.display = 'none';
        }
      });
      
      // Also hide duplicate items with these URLs
      document.querySelectorAll('.news-item-dub').forEach(item => {
        const link = item.querySelector('a.news-title-dub');
        if (link && uninterestingUrls.has(link.href)) {
          item.style.display = 'none';
        }
      });
      
      // Update all section counters and hide empty sections
      const detailsList = document.querySelectorAll('details');
      updateEntryCounts(detailsList);
      
      // Update header stats
      updateHeaderStats();
      
      // Reset button after delay
      setTimeout(() => {
        buttonElement.textContent = originalText;
        buttonElement.disabled = false;
      }, 3000);
    } else {
      buttonElement.textContent = 'Fehler';
      setTimeout(() => {
        buttonElement.textContent = originalText;
        buttonElement.disabled = false;
      }, 2000);
    }
    
  } catch (error) {
    console.error('Error hiding uninteresting items:', error);
    buttonElement.textContent = 'Fehler';
    setTimeout(() => {
      buttonElement.textContent = originalText;
      buttonElement.disabled = false;
    }, 2000);
  }
}


// ========== Visited Links Management ==========
class VisitedLinksManager {
  constructor() {
    this.visitedLinks = new Set(JSON.parse(localStorage.getItem(VISITED_LINKS_KEY) || '[]'));
  }

  markAsVisited(url) {
    this.visitedLinks.add(url);
    this.save();
  }

  isVisited(url) {
    return this.visitedLinks.has(url);
  }

  save() {
    localStorage.setItem(VISITED_LINKS_KEY, JSON.stringify([...this.visitedLinks]));
  }

  markItemsOnPage() {
    this.markNewsItems('.news-item', 'a.news-title');
    this.markNewsItems('.news-item-dub', 'a.news-title-dub');
  }

  markNewsItems(itemSelector, linkSelector) {
    document.querySelectorAll(itemSelector).forEach(item => {
      const link = item.querySelector(linkSelector);
      if (link && this.isVisited(link.href)) {
        item.classList.add('visited');
      }
    });
  }

  attachClickHandlers() {
    this.attachHandlerToLinks('a.news-title', '.news-item');
    this.attachHandlerToLinks('a.news-title-dub', '.news-item-dub');
  }

  attachHandlerToLinks(linkSelector, itemSelector) {
    const manager = this;
    document.querySelectorAll(linkSelector).forEach(link => {
      link.addEventListener('click', function() {
        manager.markAsVisited(this.href);
        manager.markAllItemsWithUrl(this.href, itemSelector, linkSelector);
        // Update mark-as-read button visibility after marking as visited
        setTimeout(() => {
          const detailsList = document.querySelectorAll('details');
          detailsList.forEach(d => updateMarkAsReadButtonVisibility(d));
        }, 100);
      });
    });
  }

  markAllItemsWithUrl(url, itemSelector, linkSelector) {
    document.querySelectorAll(itemSelector).forEach(item => {
      const itemLink = item.querySelector(linkSelector);
      if (itemLink && itemLink.href === url) {
        item.classList.add('visited');
      }
    });
  }
  
  clear() {
    this.visitedLinks.clear();
    this.save();
  }
  
  removeVisitedClass() {
    document.querySelectorAll('.news-item, .news-item-dub').forEach(item => {
      item.classList.remove('visited');
    });
  }
}

// ========== Reset Visited Links ==========
function resetVisitedLinks() {
  if (confirm('Möchten Sie wirklich alle besuchten Links zurücksetzen?')) {
    const visitedLinksManager = window.visitedLinksManagerInstance;
    if (visitedLinksManager) {
      visitedLinksManager.clear();
      visitedLinksManager.removeVisitedClass();
      console.log('Visited links reset successfully');
    }
  }
}


// ========== Hide Uninteresting Entries Toggle ==========
function initUninterestingVisibility() {
  const items = document.querySelectorAll('.news-item.uninteresting');
  const btn = document.getElementById('toggle-uninteresting-btn');

  if (items.length === 0) {
    if (btn) btn.style.display = 'none';
    return;
  }

  // Default: hidden. Restore last user choice from localStorage.
  const shouldHide = localStorage.getItem(HIDE_UNINTERESTING_KEY) !== 'false';
  applyUninterestingVisibility(shouldHide);
}

function updateUninterestingStats() {
  // Count only from sources-section to avoid double-counting (entries appear in both sections)
  const sourcesSection = document.getElementById('sources-section');
  if (!sourcesSection) return;
  const items = sourcesSection.querySelectorAll('.news-item.uninteresting');
  const statsSpan = document.getElementById('uninteresting-stats');
  if (!statsSpan) return;
  if (items.length === 0) {
    statsSpan.innerHTML = '';
    return;
  }
  // Count only items not already hidden by the active time/star filter, and not visited
  const affectedCount = Array.from(items).filter(item => {
    if (item.classList.contains('visited')) return false;
    if (currentFilterValue !== null && shouldHideItem(item, currentFilterValue)) return false;
    return true;
  }).length;
  if (affectedCount === 0) {
    statsSpan.innerHTML = '';
    return;
  }
  const hide = localStorage.getItem(HIDE_UNINTERESTING_KEY) !== 'false';
  statsSpan.innerHTML = hide
    ? `<br>${affectedCount} uninteressante ausgeblendet`
    : `<br>${affectedCount} uninteressante eingeblendet`;
}

function applyUninterestingVisibility(hide) {
  const items = document.querySelectorAll('.news-item.uninteresting');
  items.forEach(item => {
    if (item.classList.contains('visited')) return;  // visited entries are never hidden by the toggle
    if (hide) {
      item.style.display = 'none';
    } else {
      // Respect the active filter: don't reveal items the filter should still hide
      const hiddenByFilter = currentFilterValue !== null && shouldHideItem(item, currentFilterValue);
      item.style.display = hiddenByFilter ? 'none' : '';
    }
  });

  const btn = document.getElementById('toggle-uninteresting-btn');
  if (btn) {
    btn.title = hide ? 'Uninteressante Einträge einblenden' : 'Uninteressante Einträge ausblenden';
    btn.style.opacity = hide ? '0.4' : '1.0';
  }

  updateUninterestingStats();

  document.querySelectorAll('details').forEach(d => updateEntryCounts([d]));
  updateHeaderStats();
}

function toggleUninterestingVisibility() {
  const currentlyHidden = localStorage.getItem(HIDE_UNINTERESTING_KEY) !== 'false';
  const newState = !currentlyHidden;
  localStorage.setItem(HIDE_UNINTERESTING_KEY, newState ? 'true' : 'false');
  applyUninterestingVisibility(newState);
}


// ========== Live Search ==========
// Search bar in the navbar. Filters purely client-side against the DOM: an
// article (`.news-item`) stays visible only when the term (case-insensitive
// substring) appears in its title OR description. Empty term shows everything.
// Uses only safe String methods (trim, toLowerCase, indexOf) - no HTML parsing,
// so special characters like < > & + in the query are treated as plain text.
function handleSearchInput() {
  const input = document.getElementById('search-input');
  currentSearchTerm = input ? input.value.trim().toLowerCase() : '';
  // Re-apply whatever time/star filter is active on top of the new search term.
  applyActiveFilters();
  updateSearchCount();
}

function updateSearchCount() {
  const countEl = document.getElementById('search-count');
  if (!countEl) return;

  if (!currentSearchTerm) {
    countEl.hidden = true;
    countEl.textContent = '';
    return;
  }

  // Count matches in the Sources section only (like updateHeaderStats) to avoid
  // double-counting entries that appear in both the Quellen and Themen sections.
  const sourcesSection = document.getElementById('sources-section');
  if (!sourcesSection) return;
  let visibleCount = 0;
  sourcesSection.querySelectorAll('.news-item').forEach(item => {
    if (getComputedStyle(item).display !== 'none') visibleCount++;
  });

  countEl.hidden = false;
  countEl.textContent = visibleCount === 1 ? '1 Artikel gefunden' : `${visibleCount} Artikel gefunden`;
}

// ========== Filtering ==========
// Single choke point for (re-)applying the currently active time/star filter
// AND the live search term to every news item. Used both when a navbar filter
// is clicked and when the search box changes, so the two never fight.
function applyActiveFilters() {
  const newsItems = document.querySelectorAll('.news-item');
  const detailsList = document.querySelectorAll('details');
  const hideUninteresting = localStorage.getItem(HIDE_UNINTERESTING_KEY) !== 'false';

  // Apply filter to ALL news items, combining time/star/search filter with uninteresting state
  newsItems.forEach(item => {
    const hiddenByFilter = shouldHideItem(item, currentFilterValue);
    const hiddenByUninteresting = hideUninteresting
      && item.classList.contains('uninteresting')
      && !item.classList.contains('visited');  // visited entries are never hidden by the toggle
    item.style.display = (hiddenByFilter || hiddenByUninteresting) ? 'none' : '';
  });

  updateEntryCounts(detailsList);
  updateHeaderStats();
  updateUninterestingStats();
}

function filterNewsItems(value) {
  currentFilterValue = value === '<none>' ? null : value;

  if (value === '<none>') {
    const newsItems = document.querySelectorAll('.news-item');
    const detailsList = document.querySelectorAll('details');
    resetFilters(newsItems, detailsList);
    if (currentSearchTerm) {
      // Keep a live search active on top of the reset
      applyActiveFilters();
    } else {
      applyUninterestingVisibility(localStorage.getItem(HIDE_UNINTERESTING_KEY) !== 'false');
    }
    return;
  }

  applyActiveFilters();
}

function resetFilters(newsItems, detailsList) {
  newsItems.forEach(item => item.style.display = '');
  detailsList.forEach(d => d.removeAttribute('open'));
  updateEntryCounts(detailsList);
  updateHeaderStats();
}

function shouldHideItem(item, filterValue) {
  const title = item.querySelector('.news-title')?.textContent || '';
  const description = item.querySelector('.news-description')?.textContent || '';
  const hoursAgo = extractHoursAgo(item);

  // Live search overlay: if a search term is active, the item must match it
  // (case-insensitive substring over title OR description), independent of
  // whatever time/star filter is currently active.
  if (currentSearchTerm) {
    const searchHaystack = (title + ' ' + description).toLowerCase();
    if (searchHaystack.indexOf(currentSearchTerm) === -1) {
      return true;
    }
  }

  if (typeof filterValue === 'number' || !isNaN(parseInt(filterValue))) {
    return hoursAgo > parseInt(filterValue);
  } else if (filterValue === '*') {
    return !title.includes('⭐');
  } else if (filterValue === '💡') {
    return !item.classList.contains('ml-tagged');
  } else if (typeof filterValue === 'string' && filterValue.trim() !== '') {
    const searchText = filterValue.toLowerCase();
    return !title.toLowerCase().includes(searchText) && 
           !description.toLowerCase().includes(searchText);
  }
  return false;
}

function extractHoursAgo(item) {
  const hoursLabel = item.querySelector('.label.hours')?.textContent || '';
  const hoursMatch = hoursLabel.match(/(\d+)h/);
  return hoursMatch ? parseInt(hoursMatch[1]) : 0;
}

// ========== Section Visibility Cycling ==========
function cycleSectionVisibility() {
  const sourcesSection = document.getElementById('sources-section');
  const topicsSection = document.getElementById('topics-section');
  const sourcesSeparator = document.querySelector('.separator');
  const topicsSeparator = document.querySelectorAll('.separator')[1];
  
  if (!sourcesSection || !topicsSection) return;
  
  // Cycle through states: 0 -> 1 -> 2 -> 0
  sectionVisibilityState = (sectionVisibilityState + 1) % 3;
  
  // Save state to localStorage
  localStorage.setItem(SECTION_VISIBILITY_KEY, sectionVisibilityState.toString());
  
  // Apply visibility based on current state
  applySectionVisibility();
}

function applySectionVisibility() {
  const sourcesSection = document.getElementById('sources-section');
  const topicsSection = document.getElementById('topics-section');
  const sourcesSeparator = document.querySelector('.separator');
  const topicsSeparator = document.querySelectorAll('.separator')[1];
  
  if (!sourcesSection || !topicsSection) return;
  
  switch(sectionVisibilityState) {
    case 0: // Both visible
      sourcesSection.style.display = '';
      topicsSection.style.display = '';
      if (sourcesSeparator) sourcesSeparator.style.display = '';
      if (topicsSeparator) topicsSeparator.style.display = '';
      break;
    case 1: // Sources only
      sourcesSection.style.display = '';
      topicsSection.style.display = 'none';
      if (sourcesSeparator) sourcesSeparator.style.display = '';
      if (topicsSeparator) topicsSeparator.style.display = 'none';
      break;
    case 2: // Topics only
      sourcesSection.style.display = 'none';
      topicsSection.style.display = '';
      if (sourcesSeparator) sourcesSeparator.style.display = 'none';
      if (topicsSeparator) topicsSeparator.style.display = '';
      break;
  }
  
  // Update header stats after changing visibility
  updateHeaderStats();
}

function updateEntryCounts(detailsList) {
  detailsList.forEach(d => {
    // Only count main news items (not duplicates with class news-item-dub)
    const allNewsItems = Array.from(d.querySelectorAll('.news-item')).filter(item => 
      !item.classList.contains('news-item-dub')
    );
    const visibleCount = allNewsItems.filter(it => 
      getComputedStyle(it).display !== 'none'
    ).length;
    const span = d.querySelector('.entry-length');
    if (span) span.textContent = `[${visibleCount}]`;
    
    // Hide details section if no visible items
    if (visibleCount === 0) {
      d.style.display = 'none';
    } else {
      d.style.display = '';
    }
    
    // Update mark-as-read button visibility
    updateMarkAsReadButtonVisibility(d);
  });
}

function updateMarkAsReadButtonVisibility(detailsElement) {
  const markAsReadBtn = detailsElement.querySelector('.mark-as-read-btn');
  if (!markAsReadBtn) return;
  
  const visitedLinksManager = window.visitedLinksManagerInstance;
  if (!visitedLinksManager) return;
  
  // Get all visible news items (not duplicates)
  const newsItems = Array.from(detailsElement.querySelectorAll('.news-item:not(.news-item-dub)')).filter(item => 
    getComputedStyle(item).display !== 'none'
  );
  
  // Check if all visible items have been visited
  const allVisited = newsItems.length > 0 && newsItems.every(item => {
    const link = item.querySelector('a.news-title');
    return link && visitedLinksManager.isVisited(link.href);
  });
  
  // Hide button if all items are visited, show otherwise
  const buttonContainer = markAsReadBtn.parentElement;
  if (buttonContainer) {
    buttonContainer.style.display = allVisited ? 'none' : '';
  }
}

function updateHeaderStats() {
  // Only count items in the Sources section to avoid double counting
  const sourcesSection = document.getElementById('sources-section');
  if (!sourcesSection) return;
  
  // Select only main news items (not duplicates)
  // news-item-dub items don't have the standalone "news-item" class
  const allNewsItems = Array.from(sourcesSection.querySelectorAll('div.news-item'));
  
  const visibleNewsItems = allNewsItems.filter(item => 
    getComputedStyle(item).display !== 'none'
  );
  
  const visibleHighlighted = visibleNewsItems.filter(item => {
    const title = item.querySelector('.news-title')?.textContent || '';
    return title.includes('⭐');
  });

  const visibleMlTagged = visibleNewsItems.filter(item => item.classList.contains('ml-tagged'));

  // Find the oldest visible item to calculate time range
  let oldestHours = 0;
  visibleNewsItems.forEach(item => {
    const hoursAgo = extractHoursAgo(item);
    if (hoursAgo > oldestHours) {
      oldestHours = hoursAgo;
    }
  });

  // Update the header
  const statsElement = document.getElementById('dynamic-stats');
  if (statsElement) {
    statsElement.innerHTML = `
      <br>${visibleNewsItems.length} neue Einträge in ${oldestHours}h
      ${visibleHighlighted.length > 0 ? `<br>${visibleHighlighted.length} Einträge mit ⭐` : ''}
      ${visibleMlTagged.length > 0 ? `<br>${visibleMlTagged.length} Einträge mit 💡` : ''}
    `;
  }
}

// ========== Details State Persistence ==========
class DetailsStateManager {
  constructor() {
    this.detailsList = Array.from(document.querySelectorAll("details"));
  }

  init() {
    this.detailsList.forEach((detailsEl, idx) => {
      const key = this.getStorageKey(detailsEl, idx);
      this.restoreState(detailsEl, key);
      this.attachToggleHandler(detailsEl, key);
      this.attachScrollStabilization(detailsEl);
      this.attachLinkHandlers(detailsEl, key);
    });
  }

  getStorageKey(detailsEl, idx) {
    const rawKey = detailsEl.getAttribute("data-storage-key");
    return rawKey ? STORAGE_PREFIX + encodeURIComponent(rawKey) : STORAGE_PREFIX + "index_" + idx;
  }

  restoreState(detailsEl, key) {
    const stored = localStorage.getItem(key);
    if (stored === "true") {
      detailsEl.setAttribute("open", "");
    } else if (stored === "false") {
      detailsEl.removeAttribute("open");
    }
  }

  attachToggleHandler(detailsEl, key) {
    const manager = this;
    detailsEl.addEventListener("toggle", function() {
      if (this.open) {
        manager.closeOtherDetails(this);
      }
      manager.saveState(key, this.open);
    });
  }

  closeOtherDetails(currentDetails) {
    this.detailsList.forEach((otherDetailsEl, idx) => {
      if (otherDetailsEl !== currentDetails && otherDetailsEl.open) {
        otherDetailsEl.removeAttribute("open");
        const otherKey = this.getStorageKey(otherDetailsEl, idx);
        this.saveState(otherKey, false);
      }
    });
  }

  attachScrollStabilization(detailsEl) {
    const summaryEl = detailsEl.querySelector('summary');
    if (!summaryEl) return;

    summaryEl.addEventListener('click', function() {
      const oldTop = summaryEl.getBoundingClientRect().top;
      
      const adjustScroll = function() {
        requestAnimationFrame(function() {
          const newTop = summaryEl.getBoundingClientRect().top;
          const dy = newTop - oldTop;
          if (dy !== 0) {
            window.scrollBy(0, dy);
          }
        });
        detailsEl.removeEventListener('toggle', adjustScroll);
      };

      detailsEl.addEventListener('toggle', adjustScroll);
    });
  }

  attachLinkHandlers(detailsEl, key) {
    const links = detailsEl.querySelectorAll("a[href]");
    const manager = this;
    links.forEach(a => {
      a.addEventListener("click", () => {
        manager.saveState(key, detailsEl.open);
      }, { passive: true });
    });
  }

  saveState(key, isOpen) {
    try {
      localStorage.setItem(key, isOpen ? "true" : "false");
    } catch (e) {
      console.warn("Could not persist details state:", e);
    }
  }
}

// ========== Sorting News Items ==========
function sortNewsItems() {
  // Sort items within each details section
  document.querySelectorAll('details').forEach(detailsEl => {
    const newsItems = Array.from(detailsEl.querySelectorAll('.news-item:not(.news-item-dub)'));
    
    if (newsItems.length === 0) return;
    
    // Sort by: number of duplicates (desc), then hours_ago (asc)
    newsItems.sort((a, b) => {
      const aDuplicates = a.querySelectorAll('.news-item-dub').length;
      const bDuplicates = b.querySelectorAll('.news-item-dub').length;
      
      if (aDuplicates !== bDuplicates) {
        return bDuplicates - aDuplicates; // descending
      }
      
      // If same number of duplicates, sort by hours_ago
      const aHours = extractHoursAgo(a);
      const bHours = extractHoursAgo(b);
      return aHours - bHours; // ascending
    });
    
    // Get the parent container (after the <hr>)
    const hr = detailsEl.querySelector('hr');
    if (!hr) return;
    
    // Remember the mark-as-read button if it exists
    const markAsReadBtn = detailsEl.querySelector('.mark-as-read-btn');
    const markAsReadContainer = markAsReadBtn ? markAsReadBtn.parentElement : null;
    
    // Re-append items in sorted order
    newsItems.forEach(item => {
      detailsEl.appendChild(item);
    });
    
    // Re-append the mark-as-read button at the end if it exists
    if (markAsReadContainer) {
      detailsEl.appendChild(markAsReadContainer);
    }
  });
}

// ========== Initialization ==========
document.addEventListener("DOMContentLoaded", () => {
  // Initialize theme first
  initTheme();
  
  // Sort news items first
  sortNewsItems();
  
  const visitedLinksManager = new VisitedLinksManager();
  visitedLinksManager.markItemsOnPage();
  visitedLinksManager.attachClickHandlers();
  
  // Make visitedLinksManager globally accessible for markSectionAsRead function
  window.visitedLinksManagerInstance = visitedLinksManager;
  
  const detailsStateManager = new DetailsStateManager();
  detailsStateManager.init();

  // Apply saved section visibility state
  applySectionVisibility();
  
  // Initialize header stats
  updateHeaderStats();
  
  // Initialize mark-as-read button visibility
  const detailsList = document.querySelectorAll('details');
  detailsList.forEach(d => updateMarkAsReadButtonVisibility(d));

  // Initialize uninteresting entries visibility
  initUninterestingVisibility();
});


// ========== Settings UI (per-user / global runtime settings) ==========
// Backed by the SettingsStore: GET /{uid}/settings returns the merged
// (config.py defaults + runtime-settings.json overlay) state, PUT /{uid}/settings
// validates + persists it, and POST /{uid}/refresh triggers an immediate re-render.

let settingsState = null; // { settings, feeds, global, source_sort_order } from GET

function settingsBasePath() {
  return window.location.pathname.replace(/\/+$/, '');
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function setSettingsStatus(msg, kind) {
  const el = document.getElementById('settings-status');
  if (!el) return;
  el.className = kind === 'err' ? 'settings-status err'
    : (kind === 'ok' ? 'settings-status ok' : '');
  el.textContent = msg || '';
}

function settingsContent() {
  return document.getElementById('settings-content');
}

// --------------------------------------------------------- tag editors
function tagEditorHtml(field, values, placeholder) {
  const chips = (values || []).map((v, i) =>
    `<span class="tag-chip">${escapeHtml(v)}` +
    `<button type="button" class="tag-x" onclick="removeTag('${field}', ${i})" title="Entfernen">×</button></span>`
  ).join('');
  return `<div class="tag-list" id="${field}-list">${chips || '<span class="settings-hint">(leer)</span>'}</div>
    <div class="tag-add-row">
      <input type="text" id="${field}-add" placeholder="${placeholder}"
        onkeydown="if(event.key==='Enter'){event.preventDefault();addTag('${field}');}">
      <button type="button" class="btn" onclick="addTag('${field}')">Hinzufügen</button>
    </div>`;
}

// Commit text/checkbox input edits (feeds, sort order, consumption modes,
// global block) back into settingsState. Called before any re-render or save.
function commitDomEdits() {
  if (!settingsState) return;

  // Feeds table
  const tbody = document.getElementById('feed-table-body');
  if (tbody) {
    const feeds = [];
    tbody.querySelectorAll('tr').forEach(tr => {
      const inputs = tr.querySelectorAll('input');
      if (inputs.length < 3) return;
      const source = (inputs[0].value || '').trim();
      const url = (inputs[1].value || '').trim();
      const topic = (inputs[2].value || '').trim();
      if (!source && !url && !topic) return; // skip fully-empty row
      const feed = { source, url, topic };
      if (inputs[3].checked) feed.check_paywall = true;
      const desc = (inputs[4].value || '').trim();
      if (desc) feed.desc_filter = desc;
      feeds.push(feed);
    });
    settingsState.feeds = feeds;
  }

  // Source sort order
  const sortList = document.getElementById('sort-order-list');
  if (sortList) {
    const map = {};
    sortList.querySelectorAll('.sort-row').forEach(row => {
      const nameEl = row.querySelector('input.sort-name');
      const name = nameEl ? (nameEl.value || '').trim() : (row.getAttribute('data-sort-name') || '');
      const numEl = row.querySelector('input[type="number"]');
      const v = numEl ? parseInt(numEl.value, 10) : NaN;
      if (name && !isNaN(v)) map[name] = v;
    });
    if (settingsState.settings) settingsState.settings.source_sort_order = map;
  }

  // Consumption modes
  const modes = [];
  const cmWeb = document.getElementById('cm-web');
  const cmEmail = document.getElementById('cm-email');
  if (cmWeb && cmWeb.checked) modes.push('web');
  if (cmEmail && cmEmail.checked) modes.push('email');
  if (settingsState.settings) settingsState.settings.consumption_modes = modes;

  // Global block (curated fields)
  const globals = settingsState.global || {};
  const readInt = (id) => { const el = document.getElementById(id); if (!el || el.value === '') return null; const v = Number(el.value); return isNaN(v) ? null : v; };
  const readNum = (id) => readInt(id);
  const readBool = (id) => { const el = document.getElementById(id); return el ? el.checked : null; };
  const readCsv = (id) => { const el = document.getElementById(id); if (!el) return null; return el.value.split(',').map(s => s.trim()).filter(Boolean); };
  const setIf = (key, v) => { if (v !== null && v !== undefined) globals[key] = v; };
  setIf('LIMIT', readInt('g_LIMIT'));
  setIf('HOURS_BACK', readInt('g_HOURS_BACK'));
  setIf('SOURCE_FILTER', readCsv('g_SOURCE_FILTER'));
  setIf('ENABLE_HIDE_UNREAD', readBool('g_ENABLE_HIDE_UNREAD'));
  setIf('DEPLOY_MANIFEST', readBool('g_DEPLOY_MANIFEST'));
  setIf('PAYWALL_SCORE_THRESHOLD', readInt('g_PAYWALL_SCORE_THRESHOLD'));
  setIf('PAYWALL_REQUEST_TIMEOUT_SECONDS', readInt('g_PAYWALL_REQUEST_TIMEOUT_SECONDS'));
  setIf('PAYWALL_REQUEST_RETRIES', readInt('g_PAYWALL_REQUEST_RETRIES'));
  setIf('ML_TAG_ENABLED', readBool('g_ML_TAG_ENABLED'));
  setIf('ML_TAG_THRESHOLD', readNum('g_ML_TAG_THRESHOLD'));
  setIf('ML_RETRAIN_THRESHOLD_BYTES', readInt('g_ML_RETRAIN_THRESHOLD_BYTES'));
  setIf('ML_NEGATIVE_WEIGHT', readNum('g_ML_NEGATIVE_WEIGHT'));
  setIf('ML_NEGATIVE_CAP_MULTIPLIER', readNum('g_ML_NEGATIVE_CAP_MULTIPLIER'));
  const hourEl = document.getElementById('g_CRONTRIGGER_hour');
  const minuteEl = document.getElementById('g_CRONTRIGGER_minute');
  if (hourEl || minuteEl) {
    const h = (hourEl && hourEl.value || '').trim();
    const m = (minuteEl && minuteEl.value || '').trim();
    if (h !== '' || m !== '') globals.CRONTRIGGER = { hour: h, minute: m };
  }
  settingsState.global = globals;
}

function rerenderForm() {
  const content = settingsContent();
  if (content) content.innerHTML = buildSettingsForm(settingsState);
}

// ------------------------------------------------------------- mutations
function addTag(field) {
  commitDomEdits();
  const input = document.getElementById(field + '-add');
  const val = input ? (input.value || '').trim() : '';
  if (!val) return;
  if (!Array.isArray(settingsState.settings[field])) settingsState.settings[field] = [];
  settingsState.settings[field].push(val);
  rerenderForm();
  const ni = document.getElementById(field + '-add');
  if (ni) ni.focus();
}

function removeTag(field, idx) {
  commitDomEdits();
  if (Array.isArray(settingsState.settings[field])) {
    settingsState.settings[field].splice(idx, 1);
  }
  rerenderForm();
}

function addFeedRow() {
  commitDomEdits();
  if (!Array.isArray(settingsState.feeds)) settingsState.feeds = [];
  settingsState.feeds.push({ source: '', url: '', topic: '', check_paywall: false, desc_filter: '' });
  rerenderForm();
}

function removeFeedRow(idx) {
  commitDomEdits();
  if (Array.isArray(settingsState.feeds)) {
    settingsState.feeds.splice(idx, 1);
  }
  rerenderForm();
}

function addSortRow() {
  commitDomEdits();
  if (!settingsState.settings.source_sort_order) settingsState.settings.source_sort_order = {};
  let base = 'Neue Quelle';
  const existing = Object.keys(settingsState.settings.source_sort_order);
  let name = base;
  let n = 1;
  while (existing.indexOf(name) >= 0) { name = `${base} ${n++}`; }
  settingsState.settings.source_sort_order[name] = 0;
  rerenderForm();
}

function removeSortRow(btn) {
  commitDomEdits();
  const row = btn.closest('.sort-row');
  const nameEl = row ? row.querySelector('input.sort-name') : null;
  const name = nameEl ? (nameEl.value || '').trim() : (row ? row.getAttribute('data-sort-name') : '');
  if (name && settingsState.settings && settingsState.settings.source_sort_order) {
    delete settingsState.settings.source_sort_order[name];
  }
  rerenderForm();
}

// ------------------------------------------------------------ form build
function buildSettingsForm(payload) {
  const s = payload.settings || {};
  const feeds = payload.feeds || [];
  const g = payload.global || {};
  const modes = Array.isArray(s.consumption_modes) ? s.consumption_modes : [];
  const cmChecked = (m) => modes.indexOf(m) >= 0 ? 'checked' : '';

  const sortMap = s.source_sort_order || {};
  const sortKeys = Object.keys(sortMap).sort((a, b) => a.localeCompare(b));
  const sortRowsHtml = sortKeys.length
    ? sortKeys.map(name =>
        `<div class="sort-row" data-sort-name="${escapeHtml(name)}">` +
        `<input type="text" class="sort-name" value="${escapeHtml(name)}">` +
        `<input type="number" min="0" step="1" value="${escapeHtml(sortMap[name])}">` +
        `<button type="button" class="feed-del" onclick="removeSortRow(this)">✕</button></div>`
      ).join('')
    : '<span class="settings-hint">(keine Quellenreihenfolge definiert)</span>';

  const feedRows = feeds.length
    ? feeds.map((f, i) => `
        <tr>
          <td><input type="text" value="${escapeHtml(f.source)}"></td>
          <td><input type="url" value="${escapeHtml(f.url)}"></td>
          <td><input type="text" value="${escapeHtml(f.topic)}"></td>
          <td><input type="checkbox" ${f.check_paywall ? 'checked' : ''}></td>
          <td><input type="text" value="${escapeHtml(f.desc_filter || '')}"></td>
          <td><button type="button" class="feed-del" onclick="removeFeedRow(${i})">✕</button></td>
        </tr>`).join('')
    : '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);font-size:12px;">Keine Feeds. Fügen Sie mindestens einen hinzu.</td></tr>';

  const check = (k, label) =>
    `<label class="check-row"><input type="checkbox" id="g_${k}" ${g[k] ? 'checked' : ''}> ${label}</label>`;

  return `
    <div class="settings-section">
      <h4>Empfang</h4>
      <div class="check-row"><input type="checkbox" id="cm-web" ${cmChecked('web')}> <span>Web-Ansicht</span></div>
      <div class="check-row"><input type="checkbox" id="cm-email" ${cmChecked('email')}> <span>E-Mail-Digest</span></div>
    </div>

    <div class="settings-section">
      <h4>Filter &amp; Hervorhebung</h4>
      <label>Hervorgehobene Schlüsselwörter (⭐)</label>
      ${tagEditorHtml('highlight_keywords', s.highlight_keywords, 'Schlüsselwort…')}
      <label>Blacklist — Link-Pfad (ausblenden)</label>
      ${tagEditorHtml('blacklist_link', s.blacklist_link, 'Teilstring…')}
      <label>Blacklist — Titel (ausgeblendete Schlagworte)</label>
      ${tagEditorHtml('blacklist_title', s.blacklist_title, 'Schlagwort…')}
      <label>E-Mail-Empfänger</label>
      ${tagEditorHtml('recipients', s.recipients, 'name@domain…')}
    </div>

    <div class="settings-section">
      <h4>Quellenreihenfolge</h4>
      <div id="sort-order-list">${sortRowsHtml}</div>
      <button type="button" class="btn" onclick="addSortRow()">＋ Quelle hinzufügen</button>
    </div>

    <div class="settings-section">
      <h4>Feeds</h4>
      <table class="feed-table">
        <thead><tr><th>Quelle</th><th>URL</th><th>Thema</th><th>Paywall</th><th>desc_filter</th><th></th></tr></thead>
        <tbody id="feed-table-body">${feedRows}</tbody>
      </table>
      <button type="button" class="btn" onclick="addFeedRow()">＋ Feed hinzufügen</button>
    </div>

    <details class="settings-section">
      <summary>Globale Einstellungen</summary>
      <div class="settings-section">
        <label>LIMIT (max. Feeds pro Lauf)</label>
        <input id="g_LIMIT" class="wide-number" type="number" min="1" step="1" value="${escapeHtml(g.LIMIT)}">
        <label>HOURS_BACK (Zeitfenster in Stunden)</label>
        <input id="g_HOURS_BACK" class="wide-number" type="number" min="1" step="1" value="${escapeHtml(g.HOURS_BACK)}">
        <label>SOURCE_FILTER (Quellen, Komma-getrennt; leer = alle)</label>
        <input id="g_SOURCE_FILTER" type="text" value="${escapeHtml(Array.isArray(g.SOURCE_FILTER) ? g.SOURCE_FILTER.join(', ') : '')}">
        <label>CRONTRIGGER (E-Mail-Zeit, HH:MM)</label>
        <div style="display:flex;align-items:center;gap:4px;">
          <input id="g_CRONTRIGGER_hour" class="small-number" type="text" value="${escapeHtml((g.CRONTRIGGER && g.CRONTRIGGER.hour) || '')}">
          <span>:</span>
          <input id="g_CRONTRIGGER_minute" class="small-number" type="text" value="${escapeHtml((g.CRONTRIGGER && g.CRONTRIGGER.minute) || '')}">
        </div>
        ${check('ENABLE_HIDE_UNREAD', 'Hide-Unread-Buttons anzeigen')}
        ${check('DEPLOY_MANIFEST', 'PWA-Manifest ausliefern')}
        ${check('ML_TAG_ENABLED', 'ML-Tagging aktivieren')}
        <label>ML_TAG_THRESHOLD (0–1)</label>
        <input id="g_ML_TAG_THRESHOLD" class="wide-number" type="number" min="0" max="1" step="0.01" value="${escapeHtml(g.ML_TAG_THRESHOLD)}">
        <label>PAYWALL_SCORE_THRESHOLD (0–100)</label>
        <input id="g_PAYWALL_SCORE_THRESHOLD" class="wide-number" type="number" min="0" max="100" step="1" value="${escapeHtml(g.PAYWALL_SCORE_THRESHOLD)}">
        <label>PAYWALL_REQUEST_TIMEOUT_SECONDS</label>
        <input id="g_PAYWALL_REQUEST_TIMEOUT_SECONDS" class="wide-number" type="number" min="1" step="1" value="${escapeHtml(g.PAYWALL_REQUEST_TIMEOUT_SECONDS)}">
        <label>PAYWALL_REQUEST_RETRIES</label>
        <input id="g_PAYWALL_REQUEST_RETRIES" class="small-number" type="number" min="0" step="1" value="${escapeHtml(g.PAYWALL_REQUEST_RETRIES)}">
        <label>ML_RETRAIN_THRESHOLD_BYTES</label>
        <input id="g_ML_RETRAIN_THRESHOLD_BYTES" class="wide-number" type="number" min="0" step="1" value="${escapeHtml(g.ML_RETRAIN_THRESHOLD_BYTES)}">
        <label>ML_NEGATIVE_WEIGHT</label>
        <input id="g_ML_NEGATIVE_WEIGHT" class="wide-number" type="number" min="0" step="0.01" value="${escapeHtml(g.ML_NEGATIVE_WEIGHT)}">
        <label>ML_NEGATIVE_CAP_MULTIPLIER</label>
        <input id="g_ML_NEGATIVE_CAP_MULTIPLIER" class="wide-number" type="number" min="0" step="0.1" value="${escapeHtml(g.ML_NEGATIVE_CAP_MULTIPLIER)}">
      </div>
    </details>`;
}

// ------------------------------------------------------------- open/close
async function openSettings() {
  const overlay = document.getElementById('settings-overlay');
  if (!overlay) return;
  overlay.hidden = false;
  setSettingsStatus('', '');
  const content = settingsContent();
  content.innerHTML = '<p>Lade Einstellungen…</p>';
  const saveBtn = document.getElementById('settings-save-btn');
  if (saveBtn) saveBtn.disabled = true;
  try {
    const resp = await fetch(`${settingsBasePath()}/settings`);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    settingsState = await resp.json();
    content.innerHTML = buildSettingsForm(settingsState);
    if (saveBtn) saveBtn.disabled = false;
  } catch (err) {
    content.innerHTML = '<p class="settings-hint" style="color:var(--accent-red);">Fehler beim Laden der Einstellungen.</p>';
    setSettingsStatus(`Konnte Einstellungen nicht laden: ${err.message}`, 'err');
  }
}

function closeSettings() {
  const overlay = document.getElementById('settings-overlay');
  if (overlay) overlay.hidden = true;
  setSettingsStatus('', '');
}

// ----------------------------------------------------------------- save
async function saveSettings() {
  commitDomEdits();
  if (!settingsState) return;
  const saveBtn = document.getElementById('settings-save-btn');
  if (saveBtn) saveBtn.disabled = true;
  const payload = {
    settings: settingsState.settings || {},
    feeds: settingsState.feeds || [],
    global: settingsState.global || {},
  };
  setSettingsStatus('Speichere…', 'ok');
  try {
    const resp = await fetch(`${settingsBasePath()}/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      let msg = `Speichern fehlgeschlagen (HTTP ${resp.status})`;
      try {
        const j = await resp.json();
        if (j && j.details) msg += ': ' + (Array.isArray(j.details) ? j.details.join('; ') : j.error || '');
        else if (j && j.error) msg += ': ' + j.error;
      } catch (e) { /* ignore */ }
      setSettingsStatus(msg, 'err');
      if (saveBtn) saveBtn.disabled = false;
      return;
    }
    setSettingsStatus('Gespeichert. Aktualisiere…', 'ok');
    // Immediate re-render so the new settings take effect right away.
    try {
      await fetch(`${settingsBasePath()}/refresh`, { method: 'POST' });
    } catch (e) { /* refresh failure is non-fatal for persistence */ }
    // Reload to display the freshly rendered data.
    window.location.reload();
  } catch (err) {
    setSettingsStatus(`Netzwerkfehler beim Speichern: ${err.message}`, 'err');
    if (saveBtn) saveBtn.disabled = false;
  }
}

async function reloadApp() {
  // Reload config.py at runtime (new portals/feeds) and re-render all news.
  const btn = document.getElementById('settings-reload-btn');
  if (btn) btn.disabled = true;
  setSettingsStatus('Lade Konfiguration neu…', 'ok');
  try {
    const resp = await fetch(`${settingsBasePath()}/reload`, { method: 'POST' });
    if (!resp.ok) {
      let msg = `Neuladen fehlgeschlagen (HTTP ${resp.status})`;
      try {
        const j = await resp.json();
        if (j && j.error) msg += ': ' + j.error;
      } catch (e) { /* ignore */ }
      setSettingsStatus(msg, 'err');
      if (btn) btn.disabled = false;
      return;
    }
    setSettingsStatus('Konfiguration neu geladen. Aktualisiere…', 'ok');
    window.location.reload();
  } catch (err) {
    setSettingsStatus(`Netzwerkfehler beim Neuladen: ${err.message}`, 'err');
    if (btn) btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Render-Progress banner (cold start / reload)
// ---------------------------------------------------------------------------

async function pollRenderStatus() {
  const banner = document.getElementById('render-progress-banner');
  if (!banner) return;
  const uid = banner.dataset.uid || '';
  if (!uid) return;
  try {
    const resp = await fetch(`/${uid}/render_status`, { cache: 'no-store' });
    if (!resp.ok) return;
    const st = await resp.json();
    const pct = st.percent ?? 0;
    const detail = st.message || '';
    const textEl = banner.querySelector('.render-progress-text');
    const detailEl = banner.querySelector('.render-progress-detail');
    if (textEl) textEl.textContent = `Feeds werden analysiert… ${pct}%`;
    if (detailEl) detailEl.textContent = `${detail} (${st.done_feeds || 0}/${st.total_feeds || 0})`;
    if (st.status === 'done') {
      // Render finished: hide banner and reload so the full list appears.
      banner.style.display = 'none';
      window.location.reload();
      return;
    }
  } catch (e) { /* transient; keep polling */ }
  setTimeout(pollRenderStatus, 3000);
}

document.addEventListener('DOMContentLoaded', pollRenderStatus);
