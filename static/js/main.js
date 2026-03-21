$(document).ready(function () {
    loadPlaylists();
    addBackButton();
});

let currentUserId = null;

function loadPlaylists() {
    $.get('/get-playlists')
        .done(function (response) {
            const grid = $('#playlistGrid');
            grid.empty();
            currentUserId = response.user_id;

            if (!response.playlists || response.playlists.length === 0) {
                grid.html(`
                    <div style="grid-column:1/-1; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:5rem 0; color:#bbc9cf; text-align:center;">
                        <span class="material-symbols-outlined" style="font-size:3rem; color:rgba(255,255,255,0.15); margin-bottom:1rem;">playlist_add</span>
                        <p style="font-size:0.875rem;">No playlists yet — add one to get started.</p>
                    </div>
                `);
                return;
            }

            response.playlists.forEach(function (playlist) {
                const hasAnalysis = playlist.has_analysis;
                const encodedCmd  = playlist.m3u_editor_command ? encodeURIComponent(playlist.m3u_editor_command) : '';

                const adminBtn = window.location.search.includes('admin=true') ? `
                    <button class="btn original-analysis-btn action-chip"
                            onclick="viewOriginalAnalysis('${playlist.name}')"
                            ${hasAnalysis ? '' : 'disabled'}
                            title="Classic analysis view">Classic</button>
                ` : '';

                const card = `
                    <div class="ambient-glow" style="
                        background: #1c1b1b; border-radius: 0.75rem; padding: 1.5rem;
                        transition: all 0.3s; display: flex; flex-direction: column;">

                        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:1.25rem;">
                            <button onclick="openMirrorModal(${currentUserId}, '${escapeHtml(playlist.name)}')"
                                    title="Manage alt servers / mirrors"
                                    style="background:#353534; padding:0.6rem; border-radius:0.625rem; border:none; cursor:pointer; display:flex; align-items:center; transition:background 0.15s;"
                                    onmouseover="this.style.background='#2a2a2a'" onmouseout="this.style.background='#353534'">
                                <span class="material-symbols-outlined" style="color:#00d4ff; font-size:1.25rem; font-variation-settings:'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 24;">playlist_play</span>
                            </button>
                            <span style="font-size:0.65rem; font-weight:700; padding:0.2rem 0.6rem; border-radius:9999px; background:#201f1f; color:#a8e8ff; text-transform:uppercase; letter-spacing:0.06em; font-family:'Inter',sans-serif;">
                                ${escapeHtml(playlist.source)}
                            </span>
                        </div>

                        <h3 style="font-family:'Manrope',sans-serif; font-weight:800; font-size:1.1rem; color:#e5e2e1; letter-spacing:-0.02em; margin-bottom:0.25rem;">${escapeHtml(playlist.name)}</h3>

                        <div style="display:flex; gap:1.25rem; margin:1rem 0 1.25rem; flex-wrap:wrap;">
                            <div style="text-align:center;">
                                <div style="font-family:'Manrope',sans-serif; font-weight:800; font-size:1.2rem; color:#00d4ff;">${playlist.total_channels || 0}</div>
                                <div style="font-size:0.6rem; color:rgba(255,255,255,0.35); text-transform:uppercase; letter-spacing:0.07em;">Channels</div>
                            </div>
                            <div style="text-align:center;">
                                <div style="font-family:'Manrope',sans-serif; font-weight:800; font-size:1.2rem; color:rgba(255,255,255,0.6);">${playlist.total_movies || 0}</div>
                                <div style="font-size:0.6rem; color:rgba(255,255,255,0.35); text-transform:uppercase; letter-spacing:0.07em;">Movies</div>
                            </div>
                            <div style="text-align:center;">
                                <div style="font-family:'Manrope',sans-serif; font-weight:800; font-size:1.2rem; color:rgba(255,255,255,0.6);">${playlist.total_series || 0}</div>
                                <div style="font-size:0.6rem; color:rgba(255,255,255,0.35); text-transform:uppercase; letter-spacing:0.07em;">Series</div>
                            </div>
                            <div style="text-align:center;">
                                <div style="font-family:'Manrope',sans-serif; font-weight:800; font-size:1.2rem; color:rgba(255,255,255,0.6);">${playlist.total_epg_matches || 0}</div>
                                <div style="font-size:0.6rem; color:rgba(255,255,255,0.35); text-transform:uppercase; letter-spacing:0.07em;">EPG</div>
                            </div>
                        </div>

                        <div style="display:flex; flex-wrap:wrap; gap:0.4rem; padding-top:1rem; margin-top:auto;">
                            <button class="btn edit-btn action-chip"          onclick="editPlaylist('${playlist.name}')">Edit</button>
                            <button class="btn analyze-btn action-chip"       onclick="analyzePlaylist('${playlist.name}')">Analyze</button>
                            <button class="btn content-analysis-btn action-chip action-chip-primary"
                                    onclick="viewEnhancedAnalysis('${playlist.name}')"
                                    ${hasAnalysis ? '' : 'disabled'}>Content</button>
                            ${adminBtn}
                            <button class="btn optimize-btn action-chip action-chip-accent"
                                    onclick="optimizePlaylist('${playlist.name}')"
                                    ${hasAnalysis ? '' : 'disabled'}
                                    data-command="${encodedCmd}">Optimize</button>
                            <button class="btn delete-btn action-chip action-chip-danger" onclick="deletePlaylist('${playlist.name}')">Delete</button>
                        </div>
                    </div>
                `;
                grid.append(card);
            });
        })
        .fail(function (error) {
            console.error('Error loading playlists:', error);
            $('#playlistGrid').html(`
                <div style="grid-column:1/-1; text-align:center; padding:4rem 0; color:rgba(255,255,255,0.3); font-size:0.875rem;">
                    Failed to load playlists. Please refresh.
                </div>
            `);
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
    switch (source) {
        case 'API Line':
            $('#apiLineModal').modal('show');
            break;
        case 'M3U Url':
            $('#m3uUrlModal').modal('show');
            break;
        case 'M3U File':
            $('#m3uFileModal').modal('show');
            break;
        case 'Xtream API':
            $('#xtreamApiModal').modal('show');
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

function submitXtreamApi() {
    const formData = new FormData();
    formData.append('name', $('#playlistName').val());
    formData.append('source', 'Xtream API');
    formData.append('server', $('#xtream_server').val());
    formData.append('username', $('#xtream_username').val());
    formData.append('password', $('#xtream_password').val());
    formData.append('include_vod', $('#include_vod').is(':checked'));
    formData.append('include_series', $('#include_series').is(':checked'));
    formData.append('include_proxy', $('#include_proxy').is(':checked'));

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

let _jobPollTimer = null;
let _jobStartTime = null;
let _activeJobId  = null;

function _showToast(msg, type) {
    const toast = document.createElement('div');
    const bg = type === 'success' ? 'rgba(0,160,90,0.95)' : 'rgba(180,35,35,0.95)';
    toast.style.cssText = `background:${bg}; color:#fff; padding:0.75rem 1.1rem; border-radius:0.5rem;
        font-size:0.82rem; font-family:Inter,sans-serif; max-width:340px; pointer-events:auto;
        cursor:pointer; box-shadow:0 4px 24px rgba(0,0,0,0.5); line-height:1.4;`;
    toast.textContent = msg;
    toast.onclick = () => toast.remove();
    document.getElementById('toastContainer').appendChild(toast);
    setTimeout(() => { if (toast.parentNode) toast.remove(); }, 7000);
}

function _updateProcessingUI(data) {
    document.getElementById('statusMessage').textContent = data.step || '…';
    const steps = (data.steps || []).slice(-6);
    document.getElementById('processingSteps').innerHTML =
        steps.map(s => `<div>${s}</div>`).join('');
    if (_jobStartTime) {
        const elapsed = Math.floor((Date.now() - _jobStartTime) / 1000);
        const m = Math.floor(elapsed / 60), s = elapsed % 60;
        document.getElementById('processingElapsed').textContent =
            m > 0 ? `${m}m ${s}s` : `${s}s`;
    }
}

function _pollJob(jobId) {
    _jobPollTimer = setTimeout(function () {
        $.get('/job-status/' + jobId)
            .done(function (data) {
                _updateProcessingUI(data);
                if (data.status === 'running') {
                    _pollJob(jobId);
                } else if (data.status === 'complete') {
                    _activeJobId = null;
                    $('#processingStatus').hide();
                    loadPlaylists();
                    _showToast(
                        data.analyzed
                            ? 'Playlist ready! Content analysis complete.'
                            : 'Playlist added. Run Analyze to build content index.',
                        'success'
                    );
                } else if (data.status === 'error') {
                    _activeJobId = null;
                    $('#processingStatus').hide();
                    _showToast('Processing failed: ' + (data.error || 'Unknown error'), 'error');
                }
            })
            .fail(function () { _pollJob(jobId); }); // retry on network blip
    }, 1500);
}

window.addEventListener('beforeunload', function (e) {
    if (_activeJobId) {
        e.preventDefault();
        e.returnValue = 'Playlist is still processing. It will continue in the background, but you may miss the completion notification.';
    }
});

function submitPlaylist(formData) {
    $.modal.close();
    _jobStartTime = Date.now();
    _updateProcessingUI({ step: 'Connecting…', steps: [] });
    $('#processingStatus').show();

    $.ajax({ url: '/process-playlist', type: 'POST', data: formData, processData: false, contentType: false })
        .done(function (response) {
            if (response.job_id) {
                _activeJobId = response.job_id;
                _pollJob(response.job_id);
            } else {
                $('#processingStatus').hide();
                _showToast('Unexpected server response', 'error');
            }
        })
        .fail(function (error) {
            $('#processingStatus').hide();
            _showToast('Failed to start: ' + (error.responseJSON?.error || 'Unknown error'), 'error');
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
            .done(function (response) {
                loadPlaylists();
                alert('Playlist deleted successfully');
            })
            .fail(function (error) {
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
        .done(function (response) {
            $('#processingStatus').hide();

            // Find the buttons for this playlist
            const contentAnalysisBtn = $(`button.content-analysis-btn[onclick="viewEnhancedAnalysis('${name}')"]`);
            const originalAnalysisBtn = $(`button.original-analysis-btn[onclick="viewOriginalAnalysis('${name}')"]`);
            const optimizeBtn = $(`button.optimize-btn[onclick="optimizePlaylist('${name}')"]`);

            // Enable all buttons
            contentAnalysisBtn.prop('disabled', false);
            originalAnalysisBtn.prop('disabled', false);
            optimizeBtn.prop('disabled', false);

            // Store any command data
            if (response.command) {
                optimizeBtn.attr('data-command', response.command);
            }

            // Reload playlists to update statistics
            loadPlaylists();

            alert('Analysis completed successfully');
        })
        .fail(function (error) {
            $('#processingStatus').hide();
            alert('Error analyzing playlist: ' + (error.responseJSON?.error || 'Unknown error'));
        });
}

function viewEnhancedAnalysis(name) {
    if (!currentUserId) {
        console.error('User ID not found');
        return;
    }

    // Construct the URL to the enhanced analysis
    const analysisUrl = `/demo/enhanced/${currentUserId}/${encodeURIComponent(name)}`;

    // Navigate to the enhanced analysis page
    window.location.href = analysisUrl;
}

function viewOriginalAnalysis(name) {
    if (!currentUserId) {
        console.error('User ID not found');
        return;
    }

    // Construct the correct URL to the original analysis file
    const analysisUrl = `/static/playlists/${currentUserId}/${encodeURIComponent(name)}/analysis/content_analysis_matched.html`;

    // Navigate to the original analysis page
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
        .done(function (response) {
            $('#processingStatus').hide();
            alert('Playlist optimization completed successfully. Check the optimized folder in your playlist directory.');
        })
        .fail(function (error) {
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
            .click(function () {
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