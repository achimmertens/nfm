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


// ========== Filtering ==========
function filterNewsItems(value) {
  currentFilterValue = value === '<none>' ? null : value;

  const newsItems = document.querySelectorAll('.news-item');
  const detailsList = document.querySelectorAll('details');

  if (value === '<none>') {
    resetFilters(newsItems, detailsList);
    applyUninterestingVisibility(localStorage.getItem(HIDE_UNINTERESTING_KEY) !== 'false');
    return;
  }

  const hideUninteresting = localStorage.getItem(HIDE_UNINTERESTING_KEY) !== 'false';

  // Apply filter to ALL news items, combining time/star filter with uninteresting state
  newsItems.forEach(item => {
    const hiddenByFilter = shouldHideItem(item, value);
    const hiddenByUninteresting = hideUninteresting
      && item.classList.contains('uninteresting')
      && !item.classList.contains('visited');  // visited entries are never hidden by the toggle
    item.style.display = (hiddenByFilter || hiddenByUninteresting) ? 'none' : '';
  });

  updateEntryCounts(detailsList);
  updateHeaderStats();
  updateUninterestingStats();
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
