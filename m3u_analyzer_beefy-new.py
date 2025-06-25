import xml.etree.ElementTree as ET
from collections import defaultdict
import argparse
import re
import os
import json  # Add this impor
from pathlib import Path
from datetime import datetime
import urllib.parse

def analyze_url_pattern(url):
    """
    Analyze if a URL indicates a movie or series based on its pattern.
    Returns 'movie', 'series', or None if pattern doesn't match.
    """
    import re
    
    # Create a more flexible pattern that matches both http and https URLs
    # with any domain and port number
    url_pattern = re.compile(r'https?://[^/]+/(\w+)/')
    
    match = url_pattern.search(url)
    if match:
        content_type = match.group(1).lower()
        if content_type == 'movie':
            return 'movie'
        elif content_type == 'series':
            return 'series'
    return None

def split_no_tvg_content(no_tvg_id_groups):
    """
    Split no TVG-ID content into movies and series based on URL patterns.
    """
    movies_groups = defaultdict(list)
    series_groups = defaultdict(list)
    unmatched_groups = defaultdict(list)
    
    for group_name, channels in no_tvg_id_groups.items():
        for channel in channels:
            content_type = analyze_url_pattern(channel['url'])
            if content_type == 'movie':
                movies_groups[group_name].append(channel)
            elif content_type == 'series':
                series_groups[group_name].append(channel)
            else:
                unmatched_groups[group_name].append(channel)
    
    return dict(movies_groups), dict(series_groups), dict(unmatched_groups)


def parse_series_info(title):
    """Parse series name, season, and episode from title"""
    # Pattern for "S01 E01" or similar formats
    season_ep_pattern = re.compile(r'(.*?)S(\d+)\s*E(\d+)', re.IGNORECASE)
    match = season_ep_pattern.match(title)
    
    if match:
        series_name = match.group(1).strip()
        season = int(match.group(2))
        episode = int(match.group(3))
        return {
            'series_name': series_name,
            'season': season,
            'episode': episode,
            'is_series': True
        }
    return {
        'series_name': title,
        'season': None,
        'episode': None,
        'is_series': False
    }

def organize_series_content(channels):
    """Organize channels into series hierarchy"""
    series_dict = defaultdict(lambda: defaultdict(list))
    non_series_items = []
    
    for channel in channels:
        parsed = parse_series_info(channel['name'])
        if parsed['is_series']:
            series_dict[parsed['series_name']][parsed['season']].append({
                **channel,
                **parsed
            })
        else:
            non_series_items.append(channel)
    
    # Sort episodes within each season
    for series in series_dict.values():
        for season in series.values():
            season.sort(key=lambda x: x['episode'])
    
    return dict(series_dict), non_series_items

def generate_series_content(series_dict):
    """Generate HTML for series content with collapsible sections"""
    series_html = []
    
    for series_name, seasons in sorted(series_dict.items()):
        season_html = []
        total_episodes = sum(len(episodes) for episodes in seasons.values())
        
        for season_num, episodes in sorted(seasons.items()):
            episode_rows = []
            for episode in episodes:
                episode_rows.append(f"""
                    <tr>
                        <td>{episode['name']}</td>
                        <td>{f"S{episode['season']:02d}E{episode['episode']:02d}"}</td>
                    </tr>
                """)
            
            season_html.append(f"""
                <div class="season-content" id="season-{series_name.replace(' ', '-')}-{season_num}">
                    <h4>Season {season_num} ({len(episodes)} episodes)</h4>
                    <table>
                        <thead>
                            <tr>
                                <th>Episode Name</th>
                                <th>Episode Number</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(episode_rows)}
                        </tbody>
                    </table>
                </div>
            """)
        
        series_html.append(f"""
            <div class="series-group">
                <div class="series-header" onclick="toggleSeries('{series_name.replace(' ', '-')}')">
                    <h3>▶ {series_name}</h3>
                    <span class="episode-count">{total_episodes} episodes</span>
                </div>
                <div class="series-content" id="series-{series_name.replace(' ', '-')}">
                    {''.join(season_html)}
                </div>
            </div>
        """)
    
    return ''.join(series_html)

def generate_series_page_content(channels, group_name):
    """Generate a three-column layout for series content with interactive selection."""
    # First, organize the data
    safe_group_id = re.sub(r'[^a-zA-Z0-9]', '_', group_name)
    series_data_var = f"seriesData_{safe_group_id}"
    series_data = {}
    
    for channel in channels:
        parsed = parse_series_info(channel['name'])
        if parsed['is_series']:
            if parsed['series_name'] not in series_data:
                series_data[parsed['series_name']] = {'seasons': {}}
            
            season_num = str(parsed['season'])  # Convert season to string
            if season_num not in series_data[parsed['series_name']]['seasons']:
                series_data[parsed['series_name']]['seasons'][season_num] = []
            
            series_data[parsed['series_name']]['seasons'][season_num].append({
                'episode': parsed['episode'],
                'name': channel['name'],
                'url': channel.get('url', '')
            })
    
    # CSS for the three-column layout
    css = """
        .series-container {
            display: grid;
            grid-template-columns: minmax(200px, 1fr) minmax(200px, 1fr) minmax(300px, 2fr);
            gap: 20px;
            background: white;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            height: calc(100vh - 250px);
            min-height: 500px;
        }
        
        .column {
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 5px;
            overflow-y: auto;
            height: 100%;
        }
        
        .column-header {
            position: sticky;
            top: 0;
            background: #34495e;
            color: white;
            padding: 10px 15px;
            font-weight: bold;
            border-bottom: 2px solid #2c3e50;
        }
        
        .list-item {
            padding: 10px 15px;
            border-bottom: 1px solid #dee2e6;
            cursor: pointer;
            transition: background-color 0.2s;
        }
        
        .list-item:hover {
            background: #e9ecef;
        }
        
        .list-item.active {
            background: #007bff;
            color: white;
        }
        
        .episode-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .episode-table th,
        .episode-table td {
            padding: 8px 15px;
            border-bottom: 1px solid #dee2e6;
            text-align: left;
        }
        
        .episode-table th {
            background: #f8f9fa;
            font-weight: bold;
        }
        
        .stream-actions {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        
        .stream-actions .action-btn {
            margin: 2px 0;
        }
        
        .series-info {
            padding: 10px 15px;
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            font-size: 0.9em;
        }
        
        .total-episodes {
            color: #6c757d;
            font-size: 0.8em;
            margin-left: 5px;
        }

        .action-btn {
            display: inline-block;
            padding: 4px 8px;
            margin: 0 4px;
            border-radius: 4px;
            text-decoration: none;
            color: white;
            font-size: 12px;
            transition: background-color 0.2s;
        }

        .download-btn {
            background-color: #28a745;
        }

        .download-btn:hover {
            background-color: #218838;
        }

        .watch-btn {
            background-color: #007bff;
        }

        .watch-btn:hover {
            background-color: #0056b3;
        }

        .vlc-btn {
            background-color: #f58220; /* VLC orange color */
        }

        .vlc-btn:hover {
            background-color: #d46e1d;
        }
        
        .vlc-ios-btn {
            background-color: #007aff; /* iOS blue */
        }
        
        .vlc-ios-btn:hover {
            background-color: #0062cc;
        }
        
        .vlc-android-btn {
            background-color: #3ddc84; /* Android green */
        }
        
        .vlc-android-btn:hover {
            background-color: #2fb76d;
        }
        
        .copy-btn {
            background-color: #6c757d;
        }
        
        .copy-btn:hover {
            background-color: #5a6268;
        }
        
        .episode-table th,
        .episode-table td {
            padding: 8px 15px;
            border-bottom: 1px solid #dee2e6;
            text-align: left;
            vertical-align: middle;
        }
        
        .actions-cell {
            white-space: nowrap;
        }

        @media (max-width: 768px) {
            .stream-actions {
                flex-direction: column;
            }
            
            .action-btn {
                margin: 4px 0;
                text-align: center;
            }
        }
    """
    
    # First prepare the series list items
    series_list_items = []
    for series_name, seasons in sorted(series_data.items()):
        total_episodes = sum(len(episodes) for episodes in seasons.values())
        encoded_series_name = urllib.parse.quote(series_name)  # URL-encode series_name

        series_list_items.append(f"""
            <div class="list-item" 
                data-series="{series_name}" 
                onclick="selectSeries_{safe_group_id}(decodeURIComponent('{encoded_series_name}'))">
                {series_name}
                <span class="total-episodes">{total_episodes} episodes</span>
            </div>
        """)

    series_data_js = json.dumps(series_data)  # This will handle escaping properly

    # Then use the prepared items in the main template
    return f"""
        <style>{css}</style>
        <script>
            const {series_data_var} = {series_data_js};
            
            function selectSeries_{safe_group_id}(seriesName) {{
                // Update selection state
                currentSeries = seriesName;
                currentSeason = null;
                
                // Update UI
                document.querySelectorAll('.series-list-{safe_group_id} .list-item').forEach(item => {{
                    item.classList.remove('active');
                }});
                const selectedItem = document.querySelector(`[data-series="${{seriesName}}"]`);
                if (selectedItem) {{
                    selectedItem.classList.add('active');
                }}
                
                // Update seasons list
                const seasonsContainer = document.getElementById('seasons-list-{safe_group_id}');
                if (!seasonsContainer || !{series_data_var}[seriesName]) return;
                
                let seasonsHtml = '';
                const seasons = Object.keys({series_data_var}[seriesName].seasons)
                    .sort((a, b) => parseInt(a) - parseInt(b));
                
                seasons.forEach(season => {{
                    const episodes = {series_data_var}[seriesName].seasons[season];
                    seasonsHtml += `
                        <div class="list-item" 
                            data-season="${{season}}" 
                            onclick="selectSeason_{safe_group_id}('${{season}}')">
                            S${{season.padStart(2, '0')}}
                            <span class="total-episodes">${{episodes.length}} episodes</span>
                        </div>
                    `;
                }});
                
                seasonsContainer.innerHTML = seasonsHtml;
                document.getElementById('episodes-content-{safe_group_id}').innerHTML = '';
            }}
            
            function selectSeason_{safe_group_id}(season) {{
                if (!currentSeries || !{series_data_var}[currentSeries]) return;
                
                // Update UI
                document.querySelectorAll('.seasons-list-{safe_group_id} .list-item').forEach(item => {{
                    item.classList.remove('active');
                }});
                const selectedSeason = document.querySelector(`[data-season="${{season}}"]`);
                if (selectedSeason) {{
                    selectedSeason.classList.add('active');
                }}
                
                // Get episodes for this season
                const episodes = {series_data_var}[currentSeries].seasons[season];
                if (!episodes) return;
                
                // Sort episodes by episode number
                episodes.sort((a, b) => a.episode - b.episode);
                
                // Update episodes list
                const episodesContainer = document.getElementById('episodes-content-{safe_group_id}');
                episodesContainer.innerHTML = `
                    <table class="episode-table">
                        <thead>
                            <tr>
                                <th>Episode</th>
                                <th>Title</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${{episodes.map(ep => `
                                <tr>
                                    <td>E${{ep.episode.toString().padStart(2, '0')}}</td>
                                    <td>${{ep.name}}</td>
                                    <td class="actions-cell">
                                        ${{ep.url ? `
                                            <div class="stream-actions">
                                                <a href="${{ep.url}}" class="action-btn download-btn" download="${{ep.name}}.mkv">
                                                    <i class="fa fa-download"></i> Download
                                                </a>
                                                <a href="/watch_video?url=${{encodeURIComponent(ep.url)}}" class="action-btn watch-btn">
                                                    <i class="fa fa-play"></i> Watch
                                                </a>
                                                <a href="vlc://${{encodeURIComponent(ep.url)}}" class="action-btn vlc-btn" data-platform="desktop">
                                                    <i class="fa fa-play-circle"></i> VLC Desktop
                                                </a>
                                                <a href="vlc-x-callback://x-callback-url/stream?url=${{encodeURIComponent(ep.url)}}" class="action-btn vlc-ios-btn" data-platform="ios">
                                                    <i class="fa fa-play-circle"></i> VLC iOS
                                                </a>
                                                <a href="intent://${{encodeURIComponent(ep.url)}}#Intent;package=org.videolan.vlc;action=android.intent.action.VIEW;end" class="action-btn vlc-android-btn" data-platform="android">
                                                    <i class="fa fa-play-circle"></i> VLC Android
                                                </a>
                                                <button onclick="copyStreamUrl(this, '${{encodeURIComponent(ep.url)}}')" class="action-btn copy-btn">
                                                    <i class="fa fa-copy"></i> Copy URL
                                                </button>
                                            </div>
                                        ` : 'No stream URL available'}}
                                    </td>
                                </tr>
                            `).join('')}}
                        </tbody>
                    </table>
                `;
            }}
        </script>
        <div class="series-container">
            <div class="column">
                <div class="column-header">Series</div>
                <div class="series-list series-list-{safe_group_id}">
                    {''.join(series_list_items)}
                </div>
            </div>
            <div class="column">
                <div class="column-header">Seasons</div>
                <div id="seasons-list-{safe_group_id}" class="seasons-list seasons-list-{safe_group_id}"></div>
            </div>
            <div class="column">
                <div class="column-header">Episodes</div>
                <div id="episodes-content-{safe_group_id}" class="episodes-content"></div>
            </div>
        </div>
    """


def generate_group_content(group_name, channels, include_epg=True, is_series=False, is_movie=False):
    """Generate HTML content for a group of channels"""
    if is_series:
        return f"""
            <div class="group">
                <div class="group-header">
                    <h2>{group_name}</h2>
                    <p>{len(channels)} Items</p>
                </div>
                {generate_series_page_content(channels, group_name)}
            </div>
        """
    
    # Original table layout for non-series content
    channel_rows = []
    for channel in sorted(channels, key=lambda x: x['name']):
        # EPG status handling
        if include_epg:
            epg_status = 'epg-match' if channel['has_epg'] else 'epg-no-match'
            epg_text = '✓' if channel['has_epg'] else '✗'
            epg_column = f'<td class="{epg_status}">{epg_text}</td>'
        else:
            epg_column = ''

        # Logo handling - simple, just show if exists
        logo_class = 'movie-poster' if is_movie else 'channel-logo'
        logo_html = ''
        if channel.get('logo'):  # Only try to show logo if it exists
            logo_html = f'<img src="{channel["logo"]}" alt="{"Movie Poster" if is_movie else "Channel Logo"}" class="{logo_class}" onerror="this.style.display=\'none\'">'
            
        # Actions for movies
        if is_movie and channel.get('url', '').lower().endswith('.mkv'):
            encoded_url = urllib.parse.quote(channel['url'])
            actions_column = f"""
                <td class="actions-cell">
                    <a href="{channel['url']}" class="action-btn download-btn" download="{channel['name']}.mkv">Download</a>
                    <a href="/watch_video?url={encoded_url}" class="action-btn watch-btn">Watch</a>
                </td>
            """
        else:
            actions_column = ''
        
        # Add multi-platform VLC links
        if channel.get('url'):
            encoded_url = urllib.parse.quote(channel.get('url', ''))
            stream_cell = f"""
                <td class="stream-cell">
                    <div class="stream-actions">
                        <a href="/watch_video?url={encoded_url}" class="action-btn watch-btn">
                            <i class="fa fa-play"></i> Watch
                        </a>
                        <a href="vlc://{encoded_url}" class="action-btn vlc-btn" data-platform="desktop">
                            <i class="fa fa-play-circle"></i> VLC Desktop
                        </a>
                        <a href="vlc-x-callback://x-callback-url/stream?url={encoded_url}" class="action-btn vlc-ios-btn" data-platform="ios">
                            <i class="fa fa-play-circle"></i> VLC iOS
                        </a>
                        <a href="intent://{encoded_url}#Intent;package=org.videolan.vlc;action=android.intent.action.VIEW;end" class="action-btn vlc-android-btn" data-platform="android">
                            <i class="fa fa-play-circle"></i> VLC Android
                        </a>
                        <button onclick="copyStreamUrl(this, '{encoded_url}')" class="action-btn copy-btn">
                            <i class="fa fa-copy"></i> Copy URL
                        </button>
                    </div>
                </td>
            """
        else:
            stream_cell = "<td>No stream URL available</td>"
        
        # Always add the row, regardless of logo presence
        channel_rows.append(f"""
            <tr>
                <td class="{'poster-cell' if is_movie else 'logo-cell'}">{logo_html}</td>
                <td>{channel['name']}</td>
                {'' if is_movie else f'<td>{channel["tvg_id"]}</td>'}
                {actions_column}
                {stream_cell}
                {epg_column}
            </tr>
        """)
    
    epg_header = '<th>EPG Status</th>' if include_epg else ''
    actions_header = '<th>Actions</th>' if is_movie else ''
    
    return f"""
        <div class="group">
            <div class="group-header">
                <h2>{group_name}</h2>
                <p>{len(channels)} Items</p>
            </div>
            <table class="{'movie-table' if is_movie else 'channel-table'}">
                <thead>
                    <tr>
                        <th width="{120 if is_movie else 40}">{("Poster" if is_movie else "Logo")}</th>
                        <th>Name</th>
                        {'' if is_movie else '<th>TVG ID</th>'}
                        {actions_header}
                        <th>Stream</th>
                        {epg_header}
                    </tr>
                </thead>
                <tbody>
                    {''.join(channel_rows)}
                </tbody>
            </table>
        </div>
    """


def parse_m3u_structure(m3u_path):
    """Parse M3U file to extract ALL content, including movies and no-tvg-id entries"""
    groups = defaultdict(list)
    no_tvg_id_groups = defaultdict(list)
    
    try:
        with open(m3u_path, 'r', encoding='utf-8') as f:
            content = f.readlines()
            
        current_channel = {}
        line_number = 0
        
        print("\nParsing M3U file...")
        
        for line in content:
            line_number += 1
            line = line.strip()
            if line.startswith('#EXTINF:'):
                # Extract all relevant information
                group_match = re.search(r'group-title="([^"]+)"', line)
                tvg_id_match = re.search(r'tvg-id="([^"]*)"', line)
                name_match = re.search(r'",([^,]+)$', line)
                tvg_logo_match = re.search(r'tvg-logo="([^"]*)"', line)
                
                if group_match and name_match:
                    tvg_id = tvg_id_match.group(1) if tvg_id_match else ""
                    group_name = group_match.group(1)
                    
                    current_channel = {
                        'group': group_name,
                        'tvg_id': tvg_id,
                        'name': name_match.group(1).strip(),
                        'logo': tvg_logo_match.group(1) if tvg_logo_match else "",  # This is fine, default to empty string
                        'full_line': line,
                        'line_number': line_number,
                        'has_tvg_id': bool(tvg_id.strip())
                    }

            elif line and not line.startswith('#') and current_channel:
                # This is the URL line
                current_channel['url'] = line
                
                # Sort into appropriate dictionary based on tvg-id presence
                if current_channel['has_tvg_id']:
                    groups[current_channel['group']].append(current_channel.copy())
                else:
                    no_tvg_id_groups[current_channel['group']].append(current_channel.copy())
                    
                current_channel = {}
        
        print(f"\nFound {len(groups)} groups with tvg-id")
        print(f"Found {len(no_tvg_id_groups)} groups without tvg-id")
        
        return dict(groups), dict(no_tvg_id_groups)
        
    except Exception as e:
        print(f"Error parsing M3U file: {e}")
        import traceback
        traceback.print_exc()
        return None, None

def check_epg_matches(xml_file, groups):
    """Check which channels from M3U have EPG entries"""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # Get all unique channel IDs from EPG
        epg_channels = set()
        for programme in root.findall('.//programme'):
            channel_id = programme.get('channel', '')
            if channel_id:
                epg_channels.add(channel_id)
        
        print(f"\nFound {len(epg_channels)} unique channels in EPG")
        
        # Add EPG match information to groups
        matched_groups = defaultdict(list)
        for group, channels in groups.items():
            for channel in channels:
                channel['has_epg'] = channel['tvg_id'] in epg_channels
                matched_groups[group].append(channel)
        
        return dict(matched_groups)
    except Exception as e:
        print(f"Error checking EPG matches: {e}")
        return None



def organize_no_tvg_content(channels):
    """Split content into Movies and TV Series and organize accordingly"""
    # Pattern for detecting TV series format
    series_pattern = re.compile(r'.*?S(\d+)\s*E(\d+)', re.IGNORECASE)
    
    tv_series = defaultdict(lambda: defaultdict(list))
    movies = defaultdict(list)
    
    for channel in channels:
        match = series_pattern.match(channel['name'])
        if match:
            # Extract base series name (everything before SXX EXX)
            series_name = channel['name'][:match.start(1)-1].strip()
            season = int(match.group(1))
            episode = int(match.group(2))
            
            tv_series[channel['group']][series_name].append({
                'name': channel['name'],
                'season': season,
                'episode': episode,
                'url': channel['url']
            })
        else:
            movies[channel['group']].append(channel)
            
    return dict(tv_series), dict(movies)

def generate_no_tvg_id_content(group_name, channels):
    """Generate HTML content for no-tvg-id section with three-column layout"""
    tv_series, movies = organize_no_tvg_content(channels)
    
    css = """
        .three-column-layout {
            display: grid;
            grid-template-columns: 250px 250px 1fr;
            gap: 20px;
            background: white;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .column {
            border: 1px solid #ddd;
            border-radius: 5px;
            height: 600px;
            overflow-y: auto;
        }
        .column-header {
            padding: 10px;
            background: #34495e;
            color: white;
            position: sticky;
            top: 0;
        }
        .item-list {
            list-style: none;
            margin: 0;
            padding: 0;
        }
        .list-item {
            padding: 8px 12px;
            border-bottom: 1px solid #eee;
            cursor: pointer;
        }
        .list-item:hover {
            background: #f8f9fa;
        }
        .list-item.active {
            background: #e9ecef;
            font-weight: bold;
        }
        .episode-table {
            width: 100%;
            border-collapse: collapse;
        }
        .episode-table th,
        .episode-table td {
            padding: 8px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        .content-type-selector {
            margin-bottom: 20px;
        }
    """
    
    js = """
        function showSeries(seriesName) {
            // Update series selection
            document.querySelectorAll('.series-item').forEach(item => 
                item.classList.remove('active'));
            document.querySelector(`[data-series="${seriesName}"]`).classList.add('active');
            
            // Show seasons
            const seasons = seriesData[seriesName].seasons;
            const seasonList = document.getElementById('season-list');
            seasonList.innerHTML = Object.keys(seasons)
                .sort((a, b) => parseInt(a) - parseInt(b))
                .map(season => `
                    <li class="list-item season-item" 
                        data-series="${seriesName}"
                        data-season="${season}"
                        onclick="showEpisodes('${seriesName}', ${season})">
                        ${seriesName} S${season.padStart(2, '0')}
                    </li>
                `).join('');
            
            // Clear episodes
            document.getElementById('episode-list').innerHTML = '';
        }
        
        function showEpisodes(seriesName, season) {
            // Update season selection
            document.querySelectorAll('.season-item').forEach(item => 
                item.classList.remove('active'));
            document.querySelector(`[data-series="${seriesName}"][data-season="${season}"]`)
                .classList.add('active');
            
            // Show episodes
            const episodes = seriesData[seriesName].seasons[season];
            document.getElementById('episode-list').innerHTML = `
                <table class="episode-table">
                    <thead>
                        <tr>
                            <th>Episode</th>
                            <th>Title</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${episodes.map(ep => `
                            <tr>
                                <td>E${ep.episode.toString().padStart(2, '0')}</td>
                                <td>${ep.name}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        }
    """
    
    # Process series data
    series_data = {}
    for group, series_dict in tv_series.items():
        for series_name, episodes in series_dict.items():
            # Extract base series name (without season/episode)
            base_name = re.match(r'(.*?)\s*S\d+\s*E\d+', series_name).group(1).strip()
            
            if base_name not in series_data:
                series_data[base_name] = {'seasons': {}}
            
            season = str(episodes[0]['season'])
            if season not in series_data[base_name]['seasons']:
                series_data[base_name]['seasons'][season] = []
            
            series_data[base_name]['seasons'][season].extend(episodes)
    
    # Generate series list HTML
    series_list = []
    for series_name in sorted(series_data.keys()):
        series_list.append(f"""
            <li class="list-item series-item" 
                data-series="{series_name}"
                onclick="showSeries('{series_name}')">
                {series_name}
            </li>
        """)
    
    return f"""
        <style>{css}</style>
        <script>
            const seriesData = {str(series_data).replace("'", '"')};
            {js}
        </script>
        
        <div class="three-column-layout">
            <div class="column">
                <div class="column-header">Series</div>
                <ul class="item-list" id="series-list">
                    {''.join(series_list)}
                </ul>
            </div>
            
            <div class="column">
                <div class="column-header">Seasons</div>
                <ul class="item-list" id="season-list"></ul>
            </div>
            
            <div class="column">
                <div class="column-header">Episodes</div>
                <div id="episode-list"></div>
            </div>
        </div>
    """

def generate_shared_header(total_channels, total_epg_matches, total_movies, total_series, total_unmatched, m3u_editor_command):
    """Generate common header HTML used across all pages"""
    return f"""
        <div class="header">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1>M3U Content Analysis Report</h1>
                <a href="/" class="back-btn">Back to Playlists</a>
            </div>
            <div class="timestamp">Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
            <p>Total Channels with TVG-ID: {total_channels}</p>
            <p>Channels with EPG Matches: {total_epg_matches}</p>
            <p>Movies without TVG-ID: {total_movies}</p>
            <p>Series without TVG-ID: {total_series}</p>
            <p>Unmatched Content without TVG-ID: {total_unmatched}</p>
        </div>

        <div class="nav-tabs">
            <a href="content_analysis_matched.html" class="tab">With EPG ({total_epg_matches})</a>
            <a href="content_analysis_unmatched.html" class="tab">No EPG ({total_channels - total_epg_matches})</a>
            <a href="content_analysis_movies.html" class="tab">Movies ({total_movies})</a>
            <a href="content_analysis_series.html" class="tab">Series ({total_series})</a>
            <a href="content_analysis_unmatched_no_tvg.html" class="tab">Other ({total_unmatched})</a>
        </div>
    """


def generate_html_page(title, content, shared_header, css_styles, scripts="", m3u_editor_command=None):
    """Generate a complete HTML page"""
    command_div = ""
    if m3u_editor_command:
        command_div = f"""
            <div id="optimizationData" 
                 data-command="{m3u_editor_command}"
                 style="display: none;">
            </div>
        """

    # Additional scripts for platform detection and URL copying
    additional_scripts = """
        // Platform detection
        function detectPlatform() {
            const userAgent = navigator.userAgent || navigator.vendor || window.opera;
            
            // iOS detection
            if (/iPad|iPhone|iPod/.test(userAgent) && !window.MSStream) {
                return 'ios';
            }
            
            // Android detection
            if (/android/i.test(userAgent)) {
                return 'android';
            }
            
            // Default to desktop
            return 'desktop';
        }
        
        // Copy stream URL to clipboard
        function copyStreamUrl(button, url) {
            const decodedUrl = decodeURIComponent(url);
            
            // Enhanced clipboard API with fallback
            const copyToClipboard = async (text) => {
                if (navigator.clipboard && window.isSecureContext) {
                    try {
                        await navigator.clipboard.writeText(text);
                        return true;
                    } catch (err) {
                        console.warn('Clipboard API failed, falling back to execCommand', err);
                    }
                }
                
                // Fallback for older browsers or insecure contexts
                const textArea = document.createElement('textarea');
                textArea.value = text;
                textArea.style.position = 'fixed';
                textArea.style.left = '-999999px';
                textArea.style.top = '-999999px';
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                
                try {
                    const successful = document.execCommand('copy');
                    document.body.removeChild(textArea);
                    return successful;
                } catch (err) {
                    document.body.removeChild(textArea);
                    return false;
                }
            };
            
            copyToClipboard(decodedUrl).then(success => {
                const originalHTML = button.innerHTML;
                const originalStyle = button.style.cssText;
                
                if (success) {
                    // Success feedback
                    button.innerHTML = '<i class="fa fa-check"></i> Copied!';
                    button.style.backgroundColor = '#28a745';
                    button.disabled = true;
                    
                    setTimeout(() => {
                        button.innerHTML = originalHTML;
                        button.style.cssText = originalStyle;
                        button.disabled = false;
                    }, 2000);
                } else {
                    // Error feedback
                    button.innerHTML = '<i class="fa fa-exclamation"></i> Failed';
                    button.style.backgroundColor = '#dc3545';
                    
                    setTimeout(() => {
                        button.innerHTML = originalHTML;
                        button.style.cssText = originalStyle;
                    }, 2000);
                }
            });
        }
        
        // Show only relevant platform buttons
        document.addEventListener('DOMContentLoaded', function() {
            const platform = detectPlatform();
            console.log('Detected platform:', platform);
            
            // Show platform-specific buttons
            document.querySelectorAll('[data-platform]').forEach(button => {
                if (button.dataset.platform === platform) {
                    button.style.display = 'inline-block';
                    // Make platform-specific button more prominent
                    button.style.fontWeight = 'bold';
                    button.style.padding = '6px 10px';
                } else {
                    button.style.display = 'none';
                }
            });
        });
    """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - M3U Content Analysis</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            {css_styles}
            .nav-tabs {{ display: flex; gap: 10px; margin-bottom: 20px; }}
            .tab {{ 
                padding: 10px 20px;
                background: #34495e;
                color: white;
                border-radius: 5px;
                text-decoration: none;
                transition: background-color 0.3s;
            }}
            .tab:hover {{
                background: #2c3e50;
            }}
            .tab.active {{
                background: #2c3e50;
            }}
            
            /* VLC button styling */
            .vlc-btn {{
                background-color: #f58220; /* VLC orange color */
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                text-decoration: none;
                display: inline-block;
                font-size: 14px;
                transition: background-color 0.2s;
            }}
            
            .vlc-btn:hover {{
                background-color: #d46e1d;
            }}
            
            /* iOS VLC button */
            .vlc-ios-btn {{
                background-color: #007aff; /* iOS blue */
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                text-decoration: none;
                display: inline-block;
                font-size: 14px;
                transition: background-color 0.2s;
            }}
            
            .vlc-ios-btn:hover {{
                background-color: #0062cc;
            }}
            
            /* Android VLC button */
            .vlc-android-btn {{
                background-color: #3ddc84; /* Android green */
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                text-decoration: none;
                display: inline-block;
                font-size: 14px;
                transition: background-color 0.2s;
            }}
            
            .vlc-android-btn:hover {{
                background-color: #2fb76d;
            }}
            
            /* Copy URL button */
            .copy-btn {{
                background-color: #6c757d;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                border: none;
                display: inline-block;
                font-size: 14px;
                cursor: pointer;
                transition: background-color 0.2s;
            }}
            
            .copy-btn:hover {{
                background-color: #5a6268;
            }}
            
            .stream-cell {{
                white-space: nowrap;
            }}
            
            .stream-actions {{
                display: flex;
                flex-direction: column;
                gap: 5px;
            }}
            
            /* Platform info box */
            .platform-info {{
                background-color: #f8f9fa;
                padding: 15px;
                margin: 20px 0;
                border-radius: 5px;
                border-left: 4px solid #f58220;
            }}
            
            /* Responsive adjustments */
            @media (max-width: 768px) {{
                .stream-actions {{
                    flex-direction: column;
                }}
                
                .action-btn {{
                    margin: 4px 0;
                    text-align: center;
                }}
                
                .container {{
                    padding: 10px;
                }}
                
                table {{
                    display: block;
                    overflow-x: auto;
                }}
            }}
        </style>
        <script>{scripts}</script>
    </head>
    <body>
        <div class="container">
            {shared_header}
            <div class="platform-info">
                <p><strong>Stream Playback</strong>: We've detected your device type and are showing the appropriate VLC button. You can also copy the stream URL to use in any compatible player.</p>
            </div>
            <div class="section-header">
                <h2>{title}</h2>
            </div>
            {command_div}
            {content}
        </div>
        
        <script>
        {additional_scripts}
        </script>
    </body>
    </html>
    """

def generate_split_html_reports(groups, no_tvg_id_groups, matched_groups, output_dir):
    """Generate separate HTML reports for each section"""
    # Calculate statistics
    css_styles = """
        body { 
            font-family: Arial, sans-serif; 
            line-height: 1.6; 
            margin: 0; 
            padding: 20px; 
            background: #f5f5f5; 
        }
        .container { 
            max-width: 1200px; 
            margin: 0 auto; 
        }
        .header { 
            background: #2c3e50; 
            color: white; 
            padding: 20px; 
            margin-bottom: 20px; 
            border-radius: 5px; 
        }
        .group { 
            background: white; 
            padding: 20px; 
            margin-bottom: 20px; 
            border-radius: 5px; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
        }
        .group-header { 
            background: #34495e; 
            color: white; 
            padding: 10px; 
            margin: -20px -20px 20px -20px; 
            border-radius: 5px 5px 0 0; 
        }
        .epg-match { color: #27ae60; }
        .epg-no-match { color: #c0392b; }
        table { 
            width: 100%; 
            border-collapse: collapse; 
            margin-bottom: 20px; 
        }
        th, td { 
            padding: 8px; 
            text-align: left; 
            border-bottom: 1px solid #ddd; 
        }
        .command { 
            background: #f8f9fa; 
            padding: 15px; 
            border-radius: 5px; 
            overflow-x: auto; 
            white-space: pre-wrap; 
        }
        .section-header { 
            background: #34495e; 
            color: white; 
            padding: 10px; 
            margin: 20px 0; 
            border-radius: 5px; 
        }
        .series-group { margin-bottom: 10px; }
        .series-header { 
            background: #34495e; 
            color: white; 
            padding: 10px; 
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-radius: 5px;
        }
        .series-content { 
            display: none; 
            padding: 10px;
            background: white;
            border: 1px solid #ddd;
            border-radius: 0 0 5px 5px;
        }
        .season-content {
            margin: 10px 0;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 5px;
        }
        .episode-count {
            font-size: 0.9em;
            background: rgba(255,255,255,0.2);
            padding: 3px 8px;
            border-radius: 3px;
        }
        .back-btn {
            background-color: #6c757d;
            color: white;
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            text-decoration: none;
            transition: background-color 0.3s;
            display: inline-block;
        }
        
        .back-btn:hover {
            background-color: #5a6268;
            color: white;
            text-decoration: none;
        }
        
        /* Ensure proper spacing in header */
        .header h1 {
            margin: 0;
        }           
        /* Movie poster styling with strict size constraints */
        .movie-poster {
            width: 80px !important;           /* Force a fixed width */
            height: 120px !important;         /* Force a fixed height */
            object-fit: cover !important;     /* Maintain aspect ratio while covering area */
            border-radius: 4px;
            vertical-align: middle;
            transition: transform 0.3s ease;
        }

        .movie-poster:hover {
            transform: scale(2.5);
            transform-origin: center left;    /* Hover expands from left side */
            position: relative;
            z-index: 1000;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }

        .poster-cell {
            width: 80px !important;           /* Match poster width */
            min-width: 80px !important;       /* Prevent cell from expanding */
            max-width: 80px !important;       /* Ensure consistent width */
            padding: 4px !important;
            position: relative;
        }

        /* Ensure proper table layout */
        .movie-table {
            table-layout: fixed !important;
            width: 100%;
        }

        /* Override any conflicting styles */
        .movie-table img {
            max-width: 80px !important;
            max-height: 120px !important;
        }

        /* Action buttons styling */
        .actions-cell {
            white-space: nowrap;
            width: 160px;
        }

        .action-btn {
            display: inline-block;
            padding: 6px 12px;
            margin: 0 4px;
            border-radius: 4px;
            text-decoration: none;
            color: white;
            font-size: 14px;
            transition: background-color 0.2s;
        }

        .download-btn {
            background-color: #28a745;
        }

        .download-btn:hover {
            background-color: #218838;
        }

        .watch-btn {
            background-color: #007bff;
        }

        .watch-btn:hover {
            background-color: #0056b3;
        }

        /* Update movie table for the new column */
        .movie-table td {
            vertical-align: middle;
            padding: 8px;
        }



    """

    # Define JavaScript scripts
    scripts = """
        function toggleSeries(seriesId) {
            const content = document.getElementById('series-' + seriesId);
            if (content) {
                const header = content.previousElementSibling;
                if (content.style.display === 'none' || !content.style.display) {
                    content.style.display = 'block';
                    if (header && header.children[0]) {
                        header.children[0].textContent = '▼ ' + header.children[0].textContent.substring(2);
                    }
                } else {
                    content.style.display = 'none';
                    if (header && header.children[0]) {
                        header.children[0].textContent = '▶ ' + header.children[0].textContent.substring(2);
                    }
                }
            }
        }

        function showSeries(seriesName) {
            if (!seriesName) return;
            
            // Update series selection
            const allSeriesItems = document.querySelectorAll('.series-item');
            allSeriesItems.forEach(item => item.classList.remove('active'));
            
            const selectedSeries = document.querySelector(`[data-series="${seriesName}"]`);
            if (selectedSeries) {
                selectedSeries.classList.add('active');
            }
            
            // Show seasons list
            const seasonsList = document.querySelector('.seasons-list');
            if (!seasonsList) return;
            
            seasonsList.style.display = 'block';
            
            // Clear and populate seasons
            if (seriesData[seriesName]) {
                seasonsList.innerHTML = '<div class="section-title">Seasons</div>';
                Object.keys(seriesData[seriesName].seasons)
                    .sort((a, b) => parseInt(a) - parseInt(b))
                    .forEach(season => {
                        seasonsList.innerHTML += `
                            <div class="season-item" 
                                 data-series="${seriesName}" 
                                 data-season="${season}"
                                 onclick="showEpisodes('${seriesName}', ${season})">
                                Season ${season}
                                (${seriesData[seriesName].seasons[season].length} episodes)
                            </div>
                        `;
                    });
            }
            
            // Hide episodes list
            const episodesList = document.querySelector('.episodes-list');
            if (episodesList) {
                episodesList.style.display = 'none';
            }
        }

        function showEpisodes(seriesName, season) {
            if (!seriesName || !season) return;
            
            // Update season selection
            const allSeasonItems = document.querySelectorAll('.season-item');
            allSeasonItems.forEach(item => item.classList.remove('active'));
            
            const selectedSeason = document.querySelector(
                `[data-series="${seriesName}"][data-season="${season}"]`
            );
            if (selectedSeason) {
                selectedSeason.classList.add('active');
            }
            
            // Show and populate episodes list
            const episodesList = document.querySelector('.episodes-list');
            if (!episodesList || !seriesData[seriesName] || !seriesData[seriesName].seasons[season]) return;
            
            episodesList.style.display = 'block';
            const episodes = seriesData[seriesName].seasons[season];
            
            episodesList.innerHTML = `
                <div class="section-title">Episodes - Season ${season}</div>
                <table class="episodes-table">
                    <thead>
                        <tr>
                            <th>Episode</th>
                            <th>Title</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${episodes.map(ep => `
                            <tr>
                                <td>E${ep.episode.toString().padStart(2, '0')}</td>
                                <td>${ep.name}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        }
    """

    # Calculate statistics
    total_channels = sum(len(channels) for channels in matched_groups.values())
    total_epg_matches = sum(
        sum(1 for c in channels if c['has_epg'])
        for channels in matched_groups.values()
    )
    
    movies_groups, series_groups, unmatched_no_tvg = split_no_tvg_content(no_tvg_id_groups)
    total_movies = sum(len(channels) for channels in movies_groups.values())
    total_series = sum(len(channels) for channels in series_groups.values())
    total_unmatched = sum(len(channels) for channels in unmatched_no_tvg.values())
    total_no_tvg_id = total_movies + total_series + total_unmatched

    
    
    path_parts = Path(output_dir).parts
    static_index = path_parts.index('static')
    user_id = path_parts[static_index + 2]  # Get user_id from path
    playlist_name = path_parts[static_index + 3]  # Get playlist_name from path
    base_url = "http://m3u-toolkit.futurepr0n.com"
    m3u_url = f"{base_url}/static/playlists/{user_id}/{playlist_name}/tv.m3u"
    epg_url = f"{base_url}/static/playlists/{user_id}/{playlist_name}/epg.xml"
    print(f"Generated M3U URL: {m3u_url}")
    print(f"Generated EPG URL: {epg_url}")

    m3u_path = os.path.abspath('tv.m3u')
    epg_path = os.path.abspath('epg.xml')

    # Generate m3u editor command
    matched_channel_ids = {
        channel['tvg_id'].split('.')[0].lower() 
        for group in matched_groups.values() 
        for channel in group 
        if channel['has_epg']
    }


    playlist_dir = os.path.dirname(os.path.dirname(os.path.abspath('.')))
    optimized_dir = os.path.join(playlist_dir, 'optimized')
    
    m3u_editor_command = (
        './m3u-epg-editor-py3.py '
        f'-m="{m3u_url}" '
        f'-e="{epg_url}" '
        f'-g="\'{",".join(sorted(matched_channel_ids))}\'" '
        f'-d="{optimized_dir}" '
        '-gm="keep" -r=12'
    )

    # Get shared elements
    shared_header = generate_shared_header(
        total_channels=total_channels,
        total_epg_matches=total_epg_matches,
        total_movies=total_movies,
        total_series=total_series,
        total_unmatched=total_unmatched,
        m3u_editor_command=m3u_editor_command
    )

    # Create command.json file to store the command for the optimize button
    command_file = os.path.join(output_dir, 'command.json')
    with open(command_file, 'w') as f:
        json.dump({
            'channel_ids': ','.join(sorted(matched_channel_ids)),
            'total_channels': total_channels,
            'total_epg_matches': total_epg_matches,
            'total_movies': total_movies,
            'total_series': total_series,
            'total_unmatched': total_unmatched
        }, f)


    # Generate content for matched channels
    matched_content = []
    for group_name, channels in sorted(matched_groups.items()):
        matched_channels = [c for c in channels if c['has_epg']]
        if matched_channels:
            matched_content.append(generate_group_content(group_name, matched_channels, is_movie=False))

    # Generate content for unmatched channels
    unmatched_content = []
    for group_name, channels in sorted(matched_groups.items()):
        unmatched_channels = [c for c in channels if not c['has_epg']]
        if unmatched_channels:
            unmatched_content.append(generate_group_content(group_name, unmatched_channels, is_movie=False))

    # Generate content for no-tvg-id channels
    no_tvg_content = []
    for group_name, channels in sorted(no_tvg_id_groups.items()):
        no_tvg_content.append(generate_group_content(group_name, channels, include_epg=False))

    # Create separate files for each section
    files_created = []
    
    # Matched channels page
    matched_file = os.path.join(output_dir, 'content_analysis_matched.html')
    with open(matched_file, 'w', encoding='utf-8') as f:
        f.write(generate_html_page(
            "Content with EPG Matches",
            ''.join(matched_content),
            shared_header,
            css_styles,
            m3u_editor_command=m3u_editor_command
        ))
    files_created.append(matched_file)

    # Unmatched channels page
    unmatched_file = os.path.join(output_dir, 'content_analysis_unmatched.html')
    with open(unmatched_file, 'w', encoding='utf-8') as f:
        f.write(generate_html_page(
            "Content without EPG Matches",
            ''.join(unmatched_content),
            shared_header,
            css_styles
        ))
    files_created.append(unmatched_file)

     # Split no TVG-ID content
    movies_groups, series_groups, unmatched_no_tvg = split_no_tvg_content(no_tvg_id_groups)
    
    # Calculate new statistics
    total_channels = sum(len(channels) for channels in matched_groups.values())
    total_epg_matches = sum(
        sum(1 for c in channels if c['has_epg'])
        for channels in matched_groups.values()
    )
    total_movies = sum(len(channels) for channels in movies_groups.values())
    total_series = sum(len(channels) for channels in series_groups.values())
    total_unmatched = sum(len(channels) for channels in unmatched_no_tvg.values())
    
    # Update shared header to include new statistics
    shared_header = f"""
        <div class="header">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <h1>M3U Content Analysis Report</h1>
                <a href="/" class="back-btn">Back to Playlists</a>
            </div>
            <div class="timestamp">Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
            <p>Total Channels with TVG-ID: {total_channels}</p>
            <p>Channels with EPG Matches: {total_epg_matches}</p>
            <p>Movies without TVG-ID: {total_movies}</p>
            <p>Series without TVG-ID: {total_series}</p>
            <p>Unmatched Content without TVG-ID: {total_unmatched}</p>
        </div>

        <div class="nav-tabs">
            <a href="content_analysis_matched.html" class="tab">With EPG ({total_epg_matches})</a>
            <a href="content_analysis_unmatched.html" class="tab">No EPG ({total_channels - total_epg_matches})</a>
            <a href="content_analysis_movies.html" class="tab">Movies ({total_movies})</a>
            <a href="content_analysis_series.html" class="tab">Series ({total_series})</a>
            <a href="content_analysis_unmatched_no_tvg.html" class="tab">Other ({total_unmatched})</a>
        </div>
    """
    
    # Generate content for movies
    movies_file = os.path.join(output_dir, 'content_analysis_movies.html')
    movies_content = []
    for group_name, channels in sorted(movies_groups.items()):
        movies_content.append(generate_group_content(group_name, channels, include_epg=False, is_movie=True))
    
    with open(movies_file, 'w', encoding='utf-8') as f:
        f.write(generate_html_page(
            "Movies without TVG-ID",
            ''.join(movies_content),
            shared_header,
            css_styles
        ))
    
    # Generate content for series
    series_file = os.path.join(output_dir, 'content_analysis_series.html')
    series_content = []
    for group_name, channels in sorted(series_groups.items()):
        # Changed this line to include is_series=True
        series_content.append(generate_group_content(group_name, channels, include_epg=False, is_series=True))

    with open(series_file, 'w', encoding='utf-8') as f:
        f.write(generate_html_page(
            "Series without TVG-ID",
            ''.join(series_content),
            shared_header,
            css_styles,
            scripts  # Added scripts parameter
        ))
        
    # Generate content for unmatched no TVG-ID content
    unmatched_no_tvg_file = os.path.join(output_dir, 'content_analysis_unmatched_no_tvg.html')
    unmatched_content = []
    for group_name, channels in sorted(unmatched_no_tvg.items()):
        unmatched_content.append(generate_group_content(group_name, channels, include_epg=False, is_movie=False))
    
    with open(unmatched_no_tvg_file, 'w', encoding='utf-8') as f:
        f.write(generate_html_page(
            "Other Content without TVG-ID",
            ''.join(unmatched_content),
            shared_header,
            css_styles
        ))

    # Create an index page that redirects to the matched content
    index_file = os.path.join(output_dir, 'index.html')
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta http-equiv="refresh" content="0; url=content_analysis_matched.html">
        </head>
        <body>
            <p>Redirecting to <a href="content_analysis_matched.html">content analysis</a>...</p>
        </body>
        </html>
        """)
    files_created.append(index_file)
    
    return files_created, {
        'total_channels': total_channels,
        'total_epg_matches': total_epg_matches,
        'total_movies': total_movies,
        'total_series': total_series,
        'total_unmatched': total_unmatched,
        'm3u_editor_command': m3u_editor_command
    }

def main():
    parser = argparse.ArgumentParser(description='Analyze M3U content and EPG matches')
    parser.add_argument('m3u', help='Path to the M3U file')
    parser.add_argument('epg', help='Path to the EPG XML file')
    args = parser.parse_args()
    
    print(f"\nAnalyzing M3U file: {args.m3u}")
    groups, no_tvg_id_groups = parse_m3u_structure(args.m3u)
    
    if not groups and not no_tvg_id_groups:
        print("Error: Could not parse M3U file")
        return
        
    print(f"\nChecking EPG matches: {args.epg}")
    matched_groups = check_epg_matches(args.epg, groups)
    
    if matched_groups is not None:
        output_files = generate_split_html_reports(groups, no_tvg_id_groups, matched_groups, os.getcwd())
        print("\nReports generated:")
        for file in output_files:
            print(f"- {file}")
    else:
        print("Error processing files")

if __name__ == "__main__":
    main()