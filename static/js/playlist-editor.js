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

    const data = {
        groups: currentState.groups.map(group => ({
            name: group.name,
            visible: group.visible,
            channels: group.channels.map(channel => ({
                extinf: channel.extinf,
                url: channel.url,
                visible: channel.visible
            }))
        }))
    };

    fetch(window.location.href + '/save', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
        if (result.message) {
            alert('Changes saved successfully');
            currentState.changes = false;
            document.querySelector('.btn-primary').classList.remove('btn-warning');
            currentState.originalData = JSON.parse(JSON.stringify(currentState.groups));
        } else {
            throw new Error(result.error || 'Failed to save changes');
        }
    })
    .catch(error => {
        alert('Error saving changes: ' + error.message);
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
    // Implement additional group tools functionality
    alert('Group tools coming soon!');
}

function showChannelTools() {
    // Implement additional channel tools functionality
    alert('Channel tools coming soon!');
}