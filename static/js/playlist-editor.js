// static/js/playlist-editor.js

// Store current state
let currentState = {
    selectedGroup: null,
    changes: false,
    groups: JSON.parse(JSON.stringify(playlistData.groups)), // Deep copy of initial data
    originalData: JSON.parse(JSON.stringify(playlistData.groups)) // Backup for reset
};

// Initialize everything when the document is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log('Initial state:', currentState);
    updateStats();
    attachEventListeners();
});

function attachEventListeners() {
    // Group list click handling
    document.querySelectorAll('#groupList .list-item').forEach(item => {
        item.style.cursor = 'pointer';  // Make it clear items are clickable
        
        item.addEventListener('click', function(e) {
            if (!e.target.closest('.item-actions')) {
                const groupId = parseInt(this.dataset.groupId);
                displayGroupChannels(groupId);
            }
        });

        // Add event listeners for the action buttons
        const eyeBtn = item.querySelector('.eye-btn');
        const editBtn = item.querySelector('.action-btn[title="Edit"]');
        const deleteBtn = item.querySelector('.action-btn[title="Remove"]');

        if (eyeBtn) {
            eyeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                toggleGroupVisibility(parseInt(item.dataset.groupId), e);
            });
        }

        if (editBtn) {
            editBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                editGroup(parseInt(item.dataset.groupId), e);
            });
        }

        if (deleteBtn) {
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                removeGroup(parseInt(item.dataset.groupId), e);
            });
        }
    });
}

function displayGroupChannels(groupId) {
    console.log('Displaying channels for group:', groupId);
    
    // Update selection state
    document.querySelectorAll('#groupList .list-item').forEach(item => {
        item.classList.remove('selected');
    });
    
    const selectedItem = document.querySelector(`#groupList .list-item[data-group-id="${groupId}"]`);
    if (selectedItem) {
        selectedItem.classList.add('selected');
    }
    
    // Store selected group
    currentState.selectedGroup = groupId;
    
    // Get the channels for this group
    const group = currentState.groups[groupId];
    if (!group || !group.channels) {
        console.error('No channels found for group:', groupId);
        return;
    }

    const channelList = document.getElementById('channelList');
    channelList.innerHTML = ''; // Clear current channels
    
    // Add each channel to the list
    group.channels.forEach((channel, idx) => {
        const channelItem = document.createElement('div');
        channelItem.className = 'list-item';
        channelItem.dataset.channelId = idx;

        // Extract channel name from extinf
        const nameMatch = channel.extinf.match(/tvg-name="([^"]+)"/);
        const channelName = nameMatch ? nameMatch[1] : 'Unknown Channel';

        // Extract logo if present
        const logoMatch = channel.extinf.match(/tvg-logo="([^"]+)"/);
        const logoUrl = logoMatch ? logoMatch[1] : null;
        
        // Create channel info section
        const infoDiv = document.createElement('div');
        infoDiv.className = 'item-info';
        
        // Add logo if exists
        if (logoUrl) {
            const logo = document.createElement('img');
            logo.className = 'channel-logo';
            logo.src = logoUrl;
            logo.alt = '';
            infoDiv.appendChild(logo);
        }
        
        // Add channel name
        const nameSpan = document.createElement('span');
        nameSpan.className = 'channel-name';
        nameSpan.textContent = channelName;
        infoDiv.appendChild(nameSpan);
        
        // Create actions section
        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'item-actions';
        
        // Add visibility toggle button
        const visibilityBtn = document.createElement('button');
        visibilityBtn.className = 'action-btn eye-btn';
        visibilityBtn.title = 'Toggle visibility';
        visibilityBtn.innerHTML = '<i class="fas fa-eye"></i>';
        visibilityBtn.onclick = (e) => toggleChannelVisibility(visibilityBtn, e);
        actionsDiv.appendChild(visibilityBtn);
        
        // Add edit button
        const editBtn = document.createElement('button');
        editBtn.className = 'action-btn';
        editBtn.title = 'Edit';
        editBtn.innerHTML = '<i class="fas fa-edit"></i>';
        editBtn.onclick = (e) => editChannel(editBtn, e);
        actionsDiv.appendChild(editBtn);
        
        // Add delete button
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'action-btn';
        deleteBtn.title = 'Remove';
        deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
        deleteBtn.onclick = (e) => removeChannel(deleteBtn, e);
        actionsDiv.appendChild(deleteBtn);
        
        // Assemble channel item
        channelItem.appendChild(infoDiv);
        channelItem.appendChild(actionsDiv);
        channelList.appendChild(channelItem);
    });
    
    // Update header to show current group and channel count
    const channelPanelHeader = document.querySelector('.panel:nth-child(2) .panel-header h2');
    channelPanelHeader.textContent = `Channels - ${group.name} (${group.channels.length})`;
}

function toggleGroupVisibility(groupId, event) {
    event.stopPropagation();
    const group = currentState.groups[groupId];
    const button = event.currentTarget;
    const icon = button.querySelector('i');

    group.visible = !group.visible;
    button.classList.toggle('hidden');
    
    if (group.visible) {
        icon.classList.replace('fa-eye-slash', 'fa-eye');
    } else {
        icon.classList.replace('fa-eye', 'fa-eye-slash');
    }

    // Toggle all channels in the group
    group.channels.forEach(channel => {
        channel.visible = group.visible;
    });

    if (currentState.selectedGroup === groupId) {
        displayGroupChannels(groupId);
    }

    updateStats();
    markChanges();
}

function toggleChannelVisibility(button, event) {
    event.stopPropagation();
    const groupId = currentState.selectedGroup;
    const channelId = parseInt(button.closest('.list-item').dataset.channelId);
    const channel = currentState.groups[groupId].channels[channelId];

    channel.visible = !channel.visible;
    button.classList.toggle('hidden');
    
    const icon = button.querySelector('i');
    if (channel.visible) {
        icon.classList.replace('fa-eye-slash', 'fa-eye');
    } else {
        icon.classList.replace('fa-eye', 'fa-eye-slash');
    }

    updateStats();
    markChanges();
}

function removeGroup(groupId, event) {
    event.stopPropagation();
    if (!confirm('Are you sure you want to hide this group and all its channels?')) {
        return;
    }

    const group = currentState.groups[groupId];
    group.visible = false;
    group.channels.forEach(channel => channel.visible = false);

    // Update UI
    document.querySelector(`#groupList .list-item[data-group-id="${groupId}"] .eye-btn`)
        .classList.add('hidden');

    if (currentState.selectedGroup === groupId) {
        displayGroupChannels(groupId);
    }

    updateStats();
    markChanges();
}

function removeChannel(button, event) {
    event.stopPropagation();
    if (!confirm('Are you sure you want to hide this channel?')) {
        return;
    }

    const item = button.closest('.list-item');
    const channelId = parseInt(item.dataset.channelId);
    const groupId = currentState.selectedGroup;
    
    currentState.groups[groupId].channels[channelId].visible = false;
    item.querySelector('.eye-btn').classList.add('hidden');

    updateStats();
    markChanges();
}

function editGroup(groupId, event) {
    event.stopPropagation();
    const group = currentState.groups[groupId];
    const newName = prompt('Enter new name for group:', group.name);
    
    if (newName && newName !== group.name) {
        group.name = newName;
        document.querySelector(`#groupList .list-item[data-group-id="${groupId}"] .item-info span:first-child`)
            .textContent = newName;
        markChanges();
    }
}

function editChannel(button, event) {
    event.stopPropagation();
    const item = button.closest('.list-item');
    const channelId = parseInt(item.dataset.channelId);
    const groupId = currentState.selectedGroup;
    const channel = currentState.groups[groupId].channels[channelId];
    
    const nameMatch = channel.extinf.match(/tvg-name="([^"]+)"/);
    const currentName = nameMatch ? nameMatch[1] : '';
    
    const newName = prompt('Enter new name for channel:', currentName);
    if (newName && newName !== currentName) {
        // Update the extinf with the new name
        channel.extinf = channel.extinf.replace(
            /tvg-name="[^"]*"/,
            `tvg-name="${newName}"`
        );
        item.querySelector('.channel-name').textContent = newName;
        markChanges();
    }
}

function updateStats() {
    const visibleChannels = currentState.groups.reduce((total, group) => {
        return total + (group.channels ? group.channels.filter(channel => channel.visible).length : 0);
    }, 0);
    
    document.getElementById('visibleChannels').textContent = visibleChannels;
}

function markChanges() {
    currentState.changes = true;
    document.querySelector('.btn-primary').classList.add('btn-warning');
}

function saveChanges() {
    if (!currentState.changes) {
        alert('No changes to save');
        return;
    }

    // Show loading state
    const saveButton = document.querySelector('.btn-primary');
    const originalText = saveButton.textContent;
    saveButton.textContent = 'Saving...';
    saveButton.disabled = true;

    // Prepare data for saving
    const data = {
        groups: currentState.groups.map(group => ({
            name: group.name,
            visible: group.visible !== false, // Default to true if undefined
            channels: group.channels.map(channel => ({
                extinf: channel.extinf,
                url: channel.url,
                visible: channel.visible !== false // Default to true if undefined
            }))
        }))
    };

    // Get the current URL without the '/save' part
    const baseUrl = window.location.href.replace(/\/$/, '');
    const saveUrl = `${baseUrl}/save`;

    fetch(saveUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => Promise.reject(err));
        }
        return response.json();
    })
    .then(result => {
        if (result.message) {
            // Success case
            currentState.changes = false;
            currentState.originalData = JSON.parse(JSON.stringify(currentState.groups));
            saveButton.classList.remove('btn-warning');
            alert('Changes saved successfully');
        } else {
            throw new Error(result.error || 'Failed to save changes');
        }
    })
    .catch(error => {
        console.error('Save error:', error);
        alert('Error saving changes: ' + (error.message || 'Unknown error'));
    })
    .finally(() => {
        // Reset button state
        saveButton.textContent = originalText;
        saveButton.disabled = false;
    });
}

function resetChanges() {
    if (!currentState.changes) {
        alert('No changes to reset');
        return;
    }

    if (confirm('Are you sure you want to reset all changes?')) {
        currentState.groups = JSON.parse(JSON.stringify(currentState.originalData));
        currentState.changes = false;
        document.querySelector('.btn-primary').classList.remove('btn-warning');
        
        if (currentState.selectedGroup !== null) {
            displayGroupChannels(currentState.selectedGroup);
        }
        updateStats();
        
        currentState.groups.forEach((group, idx) => {
            const eyeBtn = document.querySelector(`#groupList .list-item[data-group-id="${idx}"] .eye-btn`);
            const icon = eyeBtn.querySelector('i');
            eyeBtn.classList.toggle('hidden', !group.visible);
            icon.classList.replace(
                group.visible ? 'fa-eye-slash' : 'fa-eye',
                group.visible ? 'fa-eye' : 'fa-eye-slash'
            );
        });
    }
}

function showGroupTools() {
    let dropdown = document.getElementById('groupToolsDropdown');
    
    if (!dropdown) {
        dropdown = document.createElement('div');
        dropdown.id = 'groupToolsDropdown';
        dropdown.className = 'tools-dropdown';
        dropdown.innerHTML = `
            <button class="btn" onclick="toggleAllGroups(true)">Enable All Groups</button>
            <button class="btn" onclick="toggleAllGroups(false)">Disable All Groups</button>
        `;
        
        // Get the button that triggered this
        const groupToolsBtn = document.querySelector('.panel:first-child .panel-header button');
        // Insert the dropdown right after the button
        groupToolsBtn.insertAdjacentElement('afterend', dropdown);
        
        const style = document.createElement('style');
        style.textContent = `
            .tools-dropdown {
                position: absolute;
                background: white;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                z-index: 1000;
                display: none;
                width: 200px;
                margin-top: 5px;
            }
            .tools-dropdown button {
                display: block;
                width: 100%;
                margin: 4px 0;
                text-align: left;
                padding: 8px;
            }
            .tools-dropdown button:hover {
                background: #f8f9fa;
            }
        `;
        document.head.appendChild(style);
    }

    dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
}

function toggleAllGroups(enable) {
    // Close the dropdown
    document.getElementById('groupToolsDropdown').style.display = 'none';
    
    // Update all groups' visibility
    currentState.groups.forEach((group, idx) => {
        group.visible = enable;
        
        // Update UI for each group
        const groupItem = document.querySelector(`#groupList .list-item[data-group-id="${idx}"]`);
        const eyeBtn = groupItem.querySelector('.eye-btn');
        const icon = eyeBtn.querySelector('i');
        
        eyeBtn.classList.toggle('hidden', !enable);
        if (enable) {
            icon.classList.replace('fa-eye-slash', 'fa-eye');
        } else {
            icon.classList.replace('fa-eye', 'fa-eye-slash');
        }
        
        // Update all channels in the group
        group.channels.forEach(channel => {
            channel.visible = enable;
        });
    });

    // If there's a selected group, refresh its channel display
    if (currentState.selectedGroup !== null) {
        displayGroupChannels(currentState.selectedGroup);
    }

    // Update stats and mark changes
    updateStats();
    markChanges();
}

function showChannelTools() {
    let dropdown = document.getElementById('channelToolsDropdown');
    
    if (!dropdown) {
        dropdown = document.createElement('div');
        dropdown.id = 'channelToolsDropdown';
        dropdown.className = 'tools-dropdown';
        dropdown.innerHTML = `
            <button class="btn" onclick="toggleAllChannels(true)">Enable All Channels</button>
            <button class="btn" onclick="toggleAllChannels(false)">Disable All Channels</button>
        `;
        
        const channelToolsBtn = document.querySelector('.panel:nth-child(2) .panel-header button');
        channelToolsBtn.insertAdjacentElement('afterend', dropdown);
    }

    dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
}

function toggleAllChannels(enable) {
    document.getElementById('channelToolsDropdown').style.display = 'none';
    
    if (currentState.selectedGroup === null) {
        alert('Please select a group first');
        return;
    }
    
    // Get the current group's channels
    const group = currentState.groups[currentState.selectedGroup];
    group.channels.forEach((channel, idx) => {
        channel.visible = enable;
        
        // Update UI for each channel
        const channelItem = document.querySelector(`#channelList .list-item[data-channel-id="${idx}"]`);
        const eyeBtn = channelItem.querySelector('.eye-btn');
        const icon = eyeBtn.querySelector('i');
        
        eyeBtn.classList.toggle('hidden', !enable);
        if (enable) {
            icon.classList.replace('fa-eye-slash', 'fa-eye');
        } else {
            icon.classList.replace('fa-eye', 'fa-eye-slash');
        }
    });

    updateStats();
    markChanges();
}

function downloadEditedPlaylist() {
    // Get current URL path components
    const pathComponents = window.location.pathname.split('/');
    const userId = pathComponents[2];  // Gets user_id from URL
    const playlistName = decodeURIComponent(pathComponents[3]);  // Gets playlist name without '/edit'
    
    // Construct the correct download URL for the edited m3u file
    const downloadUrl = `/playlist/${userId}/${playlistName}_edit/tv.m3u`;
    
    fetch(downloadUrl, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.blob();
    })
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${playlistName}_edit.m3u`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
    })
    .catch(error => {
        console.error('Error downloading playlist:', error);
        alert('Error downloading playlist: ' + error.message);
    });
}