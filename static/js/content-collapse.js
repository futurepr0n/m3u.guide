/**
 * Content Collapse Enhancement Script
 * Provides collapsible groups functionality for large content analysis pages
 * Improves performance by hiding large groups initially
 */

(function() {
    'use strict';
    
    // Configuration
    const CONFIG = {
        AUTO_COLLAPSE_THRESHOLD: 100,    // Auto-collapse groups with more than this many items
        LARGE_GROUP_THRESHOLD: 50,       // Warn about large groups above this threshold
        DEBOUNCE_DELAY: 300,            // Debounce delay for search in milliseconds
        PERFORMANCE_MONITORING: true     // Enable performance monitoring
    };
    
    // Global state
    let totalGroups = 0;
    let totalItems = 0;
    let collapsedGroups = 0;
    let performanceMetrics = {
        initTime: 0,
        domElements: 0,
        memoryUsage: null
    };
    
    /**
     * Initialize collapsible groups functionality
     */
    function initCollapsibleGroups() {
        const startTime = performance.now();
        
        // Find all groups in the page
        const groups = document.querySelectorAll('.group');
        totalGroups = groups.length;
        
        if (totalGroups === 0) {
            console.log('No groups found for enhancement');
            return;
        }
        
        console.log(`Initializing collapsible groups for ${totalGroups} groups`);
        
        // Process each group
        groups.forEach((group, index) => {
            processGroup(group, index);
        });
        
        // Add performance summary
        addPerformanceSummary();
        
        // Add search functionality if needed
        addSearchInterface();
        
        // Add control panel
        addControlPanel();
        
        // Record performance metrics
        performanceMetrics.initTime = performance.now() - startTime;
        performanceMetrics.domElements = document.querySelectorAll('*').length;
        
        if (performance.memory) {
            performanceMetrics.memoryUsage = {
                used: Math.round(performance.memory.usedJSHeapSize / 1024 / 1024),
                total: Math.round(performance.memory.totalJSHeapSize / 1024 / 1024)
            };
        }
        
        logPerformanceMetrics();
    }
    
    /**
     * Process individual group for collapsible functionality
     */
    function processGroup(group, index) {
        const header = group.querySelector('.group-header');
        const table = group.querySelector('.channel-table, table');
        
        if (!header || !table) {
            console.warn(`Group ${index} missing header or table`);
            return;
        }
        
        // Count items in this group
        const rows = table.querySelectorAll('tbody tr');
        const itemCount = rows.length;
        totalItems += itemCount;
        
        // Add item count to header if not present
        addItemCountToHeader(header, itemCount);
        
        // Determine if this group should be auto-collapsed
        const shouldCollapse = itemCount > CONFIG.AUTO_COLLAPSE_THRESHOLD;
        
        if (shouldCollapse) {
            collapseGroup(group, header, table, itemCount);
            collapsedGroups++;
        } else if (itemCount > CONFIG.LARGE_GROUP_THRESHOLD) {
            markLargeGroup(header, itemCount);
        }
        
        // Add click handler for expand/collapse
        addToggleHandler(group, header, table, itemCount);
        
        // Add data attributes for search functionality
        group.setAttribute('data-item-count', itemCount);
        group.setAttribute('data-group-index', index);
    }
    
    /**
     * Add item count to group header
     */
    function addItemCountToHeader(header, itemCount) {
        const existingCount = header.querySelector('.item-count');
        if (existingCount) return;
        
        const countSpan = document.createElement('span');
        countSpan.className = 'item-count';
        countSpan.textContent = ` (${itemCount.toLocaleString()} items)`;
        countSpan.style.cssText = 'opacity: 0.8; font-weight: normal; font-size: 0.9em;';
        
        const headerText = header.querySelector('h2') || header;
        headerText.appendChild(countSpan);
    }
    
    /**
     * Collapse a group
     */
    function collapseGroup(group, header, table, itemCount) {
        table.style.display = 'none';
        header.classList.add('collapsed');
        header.style.cursor = 'pointer';
        header.title = `Click to expand ${itemCount.toLocaleString()} items`;
        
        // Add collapse indicator
        addCollapseIndicator(header, true);
        
        // Add performance benefit indicator
        if (itemCount > CONFIG.AUTO_COLLAPSE_THRESHOLD) {
            addPerformanceIndicator(header);
        }
    }
    
    /**
     * Mark large groups that aren't auto-collapsed
     */
    function markLargeGroup(header, itemCount) {
        header.style.borderLeft = '4px solid #f39c12';
        header.title = `Large group: ${itemCount.toLocaleString()} items`;
        
        const warningIcon = document.createElement('span');
        warningIcon.innerHTML = ' ⚠️';
        warningIcon.style.cssText = 'color: #f39c12; font-size: 0.9em;';
        warningIcon.title = 'Large group - may affect performance';
        header.appendChild(warningIcon);
    }
    
    /**
     * Add collapse indicator to header
     */
    function addCollapseIndicator(header, collapsed = true) {
        let indicator = header.querySelector('.collapse-indicator');
        if (!indicator) {
            indicator = document.createElement('span');
            indicator.className = 'collapse-indicator';
            indicator.style.cssText = 'float: right; font-size: 1.2em; transition: transform 0.3s ease;';
            header.appendChild(indicator);
        }
        
        indicator.innerHTML = collapsed ? '▶️' : '▼️';
        indicator.style.transform = collapsed ? 'rotate(0deg)' : 'rotate(90deg)';
    }
    
    /**
     * Add performance benefit indicator
     */
    function addPerformanceIndicator(header) {
        const perfIcon = document.createElement('span');
        perfIcon.innerHTML = ' ⚡';
        perfIcon.style.cssText = 'color: #2ecc71; font-size: 0.9em; margin-left: 5px;';
        perfIcon.title = 'Auto-collapsed for better performance';
        header.appendChild(perfIcon);
    }
    
    /**
     * Add toggle handler for expand/collapse
     */
    function addToggleHandler(group, header, table, itemCount) {
        header.addEventListener('click', (e) => {
            e.preventDefault();
            toggleGroup(group, header, table, itemCount);
        });
        
        // Add keyboard support
        header.setAttribute('tabindex', '0');
        header.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                toggleGroup(group, header, table, itemCount);
            }
        });
    }
    
    /**
     * Toggle group expanded/collapsed state
     */
    function toggleGroup(group, header, table, itemCount) {
        const isCollapsed = table.style.display === 'none';
        
        if (isCollapsed) {
            // Expand
            table.style.display = '';
            header.classList.remove('collapsed');
            header.title = `Click to collapse ${itemCount.toLocaleString()} items`;
            addCollapseIndicator(header, false);
            
            // Track expansion for large groups
            if (itemCount > CONFIG.AUTO_COLLAPSE_THRESHOLD) {
                console.log(`Expanded large group with ${itemCount} items`);
            }
        } else {
            // Collapse
            table.style.display = 'none';
            header.classList.add('collapsed');
            header.title = `Click to expand ${itemCount.toLocaleString()} items`;
            addCollapseIndicator(header, true);
        }
        
        // Update summary if it exists
        updateControlPanelStats();
    }
    
    /**
     * Add performance summary to the page
     */
    function addPerformanceSummary() {
        const summary = document.createElement('div');
        summary.className = 'performance-summary';
        summary.innerHTML = `
            <div style="background: #e8f4f8; border: 1px solid #2ecc71; border-radius: 5px; 
                        padding: 15px; margin: 20px 0; font-family: Arial, sans-serif;">
                <h3 style="margin: 0 0 10px 0; color: #2c3e50; font-size: 1.1em;">
                    📊 Performance Enhancement Active
                </h3>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px;">
                    <div><strong>Total Groups:</strong> ${totalGroups.toLocaleString()}</div>
                    <div><strong>Total Items:</strong> ${totalItems.toLocaleString()}</div>
                    <div><strong>Auto-Collapsed:</strong> ${collapsedGroups.toLocaleString()}</div>
                    <div><strong>Performance Gain:</strong> ~${Math.round((collapsedGroups / totalGroups) * 100)}% faster</div>
                </div>
                <p style="margin: 10px 0 0 0; font-size: 0.9em; color: #666;">
                    💡 Large groups (${CONFIG.AUTO_COLLAPSE_THRESHOLD}+ items) auto-collapsed. Click headers to expand.
                </p>
            </div>
        `;
        
        // Insert at the beginning of the body or after header
        const container = document.querySelector('.container') || document.body;
        const header = container.querySelector('.header');
        
        if (header) {
            header.insertAdjacentElement('afterend', summary);
        } else {
            container.insertBefore(summary, container.firstChild);
        }
    }
    
    /**
     * Add search interface
     */
    function addSearchInterface() {
        if (totalItems < 100) {
            return; // Skip search for small datasets
        }
        
        const searchHtml = `
            <div class="search-interface" style="background: white; padding: 20px; margin: 20px 0; 
                                                 border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0 0 15px 0; color: #2c3e50;">🔍 Search Content</h3>
                <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                    <input type="text" id="contentSearch" placeholder="Search by name, group, or TVG ID..." 
                           style="flex: 1; min-width: 200px; padding: 10px; border: 2px solid #ddd; 
                                  border-radius: 5px; font-size: 16px;">
                    <button onclick="clearSearch()" style="padding: 10px 15px; background: #95a5a6; 
                                                           color: white; border: none; border-radius: 5px; cursor: pointer;">
                        Clear
                    </button>
                </div>
                <div id="searchStats" style="margin-top: 10px; font-size: 0.9em; color: #666;"></div>
            </div>
        `;
        
        const summary = document.querySelector('.performance-summary');
        if (summary) {
            summary.insertAdjacentHTML('afterend', searchHtml);
            initializeSearch();
        }
    }
    
    /**
     * Initialize search functionality
     */
    function initializeSearch() {
        const searchInput = document.getElementById('contentSearch');
        if (!searchInput) return;
        
        let searchTimeout;
        
        searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                performSearch(e.target.value);
            }, CONFIG.DEBOUNCE_DELAY);
        });
        
        // Update initial stats
        updateSearchStats(totalGroups, totalItems, '');
    }
    
    /**
     * Perform search across all groups
     */
    function performSearch(query) {
        const normalizedQuery = query.toLowerCase().trim();
        const groups = document.querySelectorAll('.group');
        let visibleGroups = 0;
        let visibleItems = 0;
        
        groups.forEach(group => {
            const hasMatch = searchWithinGroup(group, normalizedQuery);
            
            if (normalizedQuery === '' || hasMatch) {
                group.style.display = '';
                visibleGroups++;
                
                // Count visible items in this group
                const itemCount = parseInt(group.getAttribute('data-item-count')) || 0;
                visibleItems += itemCount;
                
                // Auto-expand groups with matches
                if (hasMatch && normalizedQuery !== '') {
                    const header = group.querySelector('.group-header');
                    const table = group.querySelector('.channel-table, table');
                    if (header && table && table.style.display === 'none') {
                        toggleGroup(group, header, table, itemCount);
                    }
                }
            } else {
                group.style.display = 'none';
            }
        });
        
        updateSearchStats(visibleGroups, visibleItems, query);
    }
    
    /**
     * Search within a specific group
     */
    function searchWithinGroup(group, query) {
        if (query === '') return true;
        
        // Search in group header
        const header = group.querySelector('.group-header');
        if (header && header.textContent.toLowerCase().includes(query)) {
            return true;
        }
        
        // Search in table rows
        const rows = group.querySelectorAll('tbody tr');
        for (let row of rows) {
            if (row.textContent.toLowerCase().includes(query)) {
                return true;
            }
        }
        
        return false;
    }
    
    /**
     * Update search statistics
     */
    function updateSearchStats(visibleGroups, visibleItems, query) {
        const statsElement = document.getElementById('searchStats');
        if (!statsElement) return;
        
        if (query.trim() === '') {
            statsElement.innerHTML = `Showing all ${totalGroups.toLocaleString()} groups, ${totalItems.toLocaleString()} items`;
        } else {
            const groupsText = visibleGroups === 1 ? 'group' : 'groups';
            const itemsText = visibleItems === 1 ? 'item' : 'items';
            statsElement.innerHTML = `Found ${visibleGroups.toLocaleString()} ${groupsText}, ${visibleItems.toLocaleString()} ${itemsText} matching "${query}"`;
        }
    }
    
    /**
     * Clear search
     */
    window.clearSearch = function() {
        const searchInput = document.getElementById('contentSearch');
        if (searchInput) {
            searchInput.value = '';
            performSearch('');
        }
    };
    
    /**
     * Add control panel for group management
     */
    function addControlPanel() {
        const controlHtml = `
            <div class="control-panel" style="background: white; padding: 15px; margin: 20px 0; 
                                             border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h3 style="margin: 0 0 15px 0; color: #2c3e50;">⚙️ Group Controls</h3>
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <button onclick="expandAllGroups()" style="padding: 8px 15px; background: #3498db; 
                                                               color: white; border: none; border-radius: 5px; cursor: pointer;">
                        Expand All
                    </button>
                    <button onclick="collapseAllGroups()" style="padding: 8px 15px; background: #e74c3c; 
                                                                 color: white; border: none; border-radius: 5px; cursor: pointer;">
                        Collapse All
                    </button>
                    <button onclick="collapseOnlyLarge()" style="padding: 8px 15px; background: #f39c12; 
                                                                 color: white; border: none; border-radius: 5px; cursor: pointer;">
                        Auto-Collapse Large
                    </button>
                </div>
                <div id="controlStats" style="margin-top: 10px; font-size: 0.9em; color: #666;"></div>
            </div>
        `;
        
        const searchInterface = document.querySelector('.search-interface');
        if (searchInterface) {
            searchInterface.insertAdjacentHTML('afterend', controlHtml);
        } else {
            const summary = document.querySelector('.performance-summary');
            if (summary) {
                summary.insertAdjacentHTML('afterend', controlHtml);
            }
        }
        
        updateControlPanelStats();
    }
    
    /**
     * Expand all groups
     */
    window.expandAllGroups = function() {
        const groups = document.querySelectorAll('.group');
        groups.forEach(group => {
            const header = group.querySelector('.group-header');
            const table = group.querySelector('.channel-table, table');
            const itemCount = parseInt(group.getAttribute('data-item-count')) || 0;
            
            if (header && table && table.style.display === 'none') {
                toggleGroup(group, header, table, itemCount);
            }
        });
        updateControlPanelStats();
    };
    
    /**
     * Collapse all groups
     */
    window.collapseAllGroups = function() {
        const groups = document.querySelectorAll('.group');
        groups.forEach(group => {
            const header = group.querySelector('.group-header');
            const table = group.querySelector('.channel-table, table');
            const itemCount = parseInt(group.getAttribute('data-item-count')) || 0;
            
            if (header && table && table.style.display !== 'none') {
                toggleGroup(group, header, table, itemCount);
            }
        });
        updateControlPanelStats();
    };
    
    /**
     * Collapse only large groups
     */
    window.collapseOnlyLarge = function() {
        const groups = document.querySelectorAll('.group');
        groups.forEach(group => {
            const header = group.querySelector('.group-header');
            const table = group.querySelector('.channel-table, table');
            const itemCount = parseInt(group.getAttribute('data-item-count')) || 0;
            
            if (itemCount > CONFIG.AUTO_COLLAPSE_THRESHOLD && header && table) {
                if (table.style.display !== 'none') {
                    toggleGroup(group, header, table, itemCount);
                }
            }
        });
        updateControlPanelStats();
    };
    
    /**
     * Update control panel statistics
     */
    function updateControlPanelStats() {
        const statsElement = document.getElementById('controlStats');
        if (!statsElement) return;
        
        const groups = document.querySelectorAll('.group');
        let expandedCount = 0;
        let collapsedCount = 0;
        
        groups.forEach(group => {
            const table = group.querySelector('.channel-table, table');
            if (table) {
                if (table.style.display === 'none') {
                    collapsedCount++;
                } else {
                    expandedCount++;
                }
            }
        });
        
        statsElement.innerHTML = `Currently: ${expandedCount} expanded, ${collapsedCount} collapsed`;
    }
    
    /**
     * Log performance metrics
     */
    function logPerformanceMetrics() {
        if (!CONFIG.PERFORMANCE_MONITORING) return;
        
        console.group('🚀 Content Collapse Performance Metrics');
        console.log(`Initialization time: ${performanceMetrics.initTime.toFixed(2)}ms`);
        console.log(`Total DOM elements: ${performanceMetrics.domElements.toLocaleString()}`);
        console.log(`Groups processed: ${totalGroups.toLocaleString()}`);
        console.log(`Items found: ${totalItems.toLocaleString()}`);
        console.log(`Auto-collapsed: ${collapsedGroups.toLocaleString()}`);
        console.log(`Performance improvement: ~${Math.round((collapsedGroups / totalGroups) * 100)}%`);
        
        if (performanceMetrics.memoryUsage) {
            console.log(`Memory usage: ${performanceMetrics.memoryUsage.used}MB / ${performanceMetrics.memoryUsage.total}MB`);
        }
        
        console.groupEnd();
    }
    
    /**
     * Initialize when DOM is ready
     */
    function initialize() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initCollapsibleGroups);
        } else {
            // DOM already loaded
            initCollapsibleGroups();
        }
    }
    
    // Start initialization
    initialize();
    
    // Export functions for external use
    window.contentCollapse = {
        expandAll: expandAllGroups,
        collapseAll: collapseAllGroups,
        collapseOnlyLarge: collapseOnlyLarge,
        search: performSearch,
        clearSearch: clearSearch,
        metrics: performanceMetrics
    };
    
})();