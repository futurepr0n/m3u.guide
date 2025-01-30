$(document).ready(function() {
    loadPlaylists();
    addBackButton();
});

let currentUserId = null;

function loadPlaylists() {
    $.get('/get-playlists')
        .done(function(response) {
            const tbody = $('#playlistTableBody');
            tbody.empty();
            
            currentUserId = response.user_id;
            
            response.playlists.forEach(function(playlist) {
                const row = $('<tr></tr>');
                
                // Add data cells
                row.append(`<td>${playlist.name}</td>`);
                row.append(`<td>${playlist.source}</td>`);
                row.append(`<td>${playlist.total_channels || 0}</td>`);
                row.append(`<td>${playlist.total_epg_matches || 0}</td>`);
                row.append(`<td>${playlist.total_movies || 0}</td>`);
                row.append(`<td>${playlist.total_series || 0}</td>`);
                row.append(`<td>${playlist.total_unmatched || 0}</td>`);
                
                // Add command cell with a collapsible pre tag
                const commandCell = $('<td data-column="command" class="hidden-command"></td>');
                if (playlist.m3u_editor_command) {
                    const pre = $('<pre style="max-width: 300px; overflow: auto; white-space: pre-wrap;"></pre>')
                        .text(playlist.m3u_editor_command);
                    commandCell.append(pre);
                } else {
                    commandCell.text('No command available');
                }
                row.append(commandCell);
                
                const actions = $('<td></td>');
                
                // Add action buttons
                actions.append(`<button class="btn edit-btn" onclick="editPlaylist('${playlist.name}')">Edit</button> `);
                actions.append(`<button class="btn delete-btn" onclick="deletePlaylist('${playlist.name}')">Delete</button> `);
                actions.append(`<button class="btn process-btn" onclick="processPlaylist('${playlist.name}')">Process</button> `);
                actions.append(`<button class="btn analyze-btn" onclick="analyzePlaylist('${playlist.name}')">Analyze</button> `);
                
                // Content Analysis button
                actions.append(`
                    <button class="btn content-analysis-btn" 
                            onclick="viewContentAnalysis('${playlist.name}')"
                            ${playlist.has_analysis ? '' : 'disabled'}>
                        Content Analysis
                    </button>
                `);
                
                // Optimize button with data attributes
                actions.append(`
                    <button class="btn optimize-btn" 
                            onclick="optimizePlaylist('${playlist.name}')"
                            ${playlist.has_analysis ? '' : 'disabled'}
                            data-command="${playlist.m3u_editor_command ? encodeURIComponent(playlist.m3u_editor_command) : ''}">
                        Optimize
                    </button>
                `);
                
                row.append(actions);
                tbody.append(row);
            });
        })
        .fail(function(error) {
            console.error('Error loading playlists:', error);
        });
}

function nextStep() {
    const name = $('#playlistName').val();
    const source = $('#playlistSource').val();
    
    if (!name || !source) {
        alert('Please fill in all required fields');
        return;
    }
    
    $.modal.close();
    switch(source) {
        case 'API Line':
            $('#apiLineModal').modal('show');
            break;
        case 'M3U Url':
            $('#m3uUrlModal').modal('show');
            break;
        case 'M3U File':
            $('#m3uFileModal').modal('show');
            break;
    }
}

function submitApiLine() {
    const formData = new FormData();
    formData.append('name', $('#playlistName').val());
    formData.append('source', 'API Line');
    formData.append('server', $('#server').val());
    formData.append('username', $('#username').val());
    formData.append('password', $('#password').val());
    
    submitPlaylist(formData);
}

function submitM3uUrl() {
    const formData = new FormData();
    formData.append('name', $('#playlistName').val());
    formData.append('source', 'M3U Url');
    formData.append('m3u_url', $('#m3uUrl').val());
    formData.append('epg_url', $('#epgUrl').val());
    
    submitPlaylist(formData);
}

function submitM3uFile() {
    const formData = new FormData();
    formData.append('name', $('#playlistName').val());
    formData.append('source', 'M3U File');
    formData.append('m3u_file', $('#m3uFile')[0].files[0]);
    formData.append('epg_file', $('#epgFile')[0].files[0]);
    
    submitPlaylist(formData);
}

function submitPlaylist(formData) {  // Correct function declaration
    $.modal.close();
    $('#processingStatus').show();
    
    $.ajax({
        url: '/process-playlist',
        type: 'POST',
        data: formData,
        processData: false,
        contentType: false
    })
    .done(function(response) {
        $('#processingStatus').hide();
        loadPlaylists();
        if (response.analyzed) {
            alert('Playlist processed and analyzed successfully');
        } else {
            alert('Playlist processed successfully but analysis failed. You can try analyzing again manually.');
        }
    })
    .fail(function(error) {
        $('#processingStatus').hide();
        alert('Error processing playlist: ' + error.responseJSON?.error || 'Unknown error');
    });
}

function editPlaylist(name) {
    if (!currentUserId) {
        console.error('User ID not found');
        return;
    }
    window.location.href = `/playlist/${currentUserId}/${encodeURIComponent(name)}/edit`;
}

function deletePlaylist(name) {
    if (confirm('Are you sure you want to delete this playlist?')) {
        $.ajax({
            url: '/delete-playlist',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ name: name })
        })
        .done(function(response) {
            loadPlaylists();
            alert('Playlist deleted successfully');
        })
        .fail(function(error) {
            alert('Error deleting playlist: ' + error.responseJSON?.error || 'Unknown error');
        });
    }
}

function analyzePlaylist(name) {
    $('#processingStatus').show();
    $('#statusMessage').text('Analyzing playlist...');
    
    $.ajax({
        url: '/analyze-playlist',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ name: name })
    })
    .done(function(response) {
        $('#processingStatus').hide();
        
        // Find the buttons for this playlist
        const contentAnalysisBtn = $(`button.content-analysis-btn[onclick="viewContentAnalysis('${name}')"]`);
        const optimizeBtn = $(`button.optimize-btn[onclick="optimizePlaylist('${name}')"]`);
        
        // Enable both buttons
        contentAnalysisBtn.prop('disabled', false);
        optimizeBtn.prop('disabled', false);
        
        // Store any command data
        if (response.command) {
            optimizeBtn.attr('data-command', response.command);
        }
        
        // Reload playlists to update statistics
        loadPlaylists();
        
        alert('Analysis completed successfully');
    })
    .fail(function(error) {
        $('#processingStatus').hide();
        alert('Error analyzing playlist: ' + (error.responseJSON?.error || 'Unknown error'));
    });
}

function viewContentAnalysis(name) {
    if (!currentUserId) {
        console.error('User ID not found');
        return;
    }
    
    // Construct the correct URL to the analysis file
    const analysisUrl = `/static/playlists/${currentUserId}/${encodeURIComponent(name)}/analysis/content_analysis_matched.html`;
    
    // Navigate to the analysis page
    window.location.href = analysisUrl;
}

function optimizePlaylist(name) {
    // Get the button element
    const optimizeBtn = $(`button.optimize-btn[onclick="optimizePlaylist('${name}')"]`);
    const encodedCommand = optimizeBtn.data('command');
    const command = encodedCommand ? decodeURIComponent(encodedCommand) : '';
    
    console.log('Optimizing playlist:', name);
    console.log('Command:', command);
    
    $('#processingStatus').show();
    $('#statusMessage').text('Optimizing playlist...');
    
    $.ajax({
        url: '/optimize-playlist',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            name: name,
            command: command
        })
    })
    .done(function(response) {
        $('#processingStatus').hide();
        alert('Playlist optimization completed successfully. Check the optimized folder in your playlist directory.');
    })
    .fail(function(error) {
        $('#processingStatus').hide();
        console.error('Optimization error:', error);
        alert('Error optimizing playlist: ' + (error.responseJSON?.error || 'Unknown error'));
    });
}

// Add this function to handle the back button
function addBackButton() {
    if (window.location.pathname.includes('/analysis')) {
        const backButton = $('<button>')
            .text('Back to Playlists')
            .addClass('btn back-btn')
            .css({
                'position': 'fixed',
                'top': '20px',
                'left': '20px',
                'z-index': '1000'
            })
            .click(function() {
                window.location.href = '/';
            });
        
        $('body').prepend(backButton);
    }
}

function getCurrentUserId() {
    // This should be replaced with your actual method of getting the current user ID
    return document.cookie.split('; ')
        .find(row => row.startsWith('user_id='))
        ?.split('=')[1];
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}