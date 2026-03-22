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
    import urllib.parse

    # Decoded URL in case it's proxied
    test_url = url.lower()
    if 'stream_proxy' in test_url:
        try:
            # Try to extract the real URL from the proxy query
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            if 'url' in params:
                test_url = params['url'][0].lower()
        except:
            pass

    # Look for common Xtream path segments
    if '/movie/' in test_url or 'action=get_vod_streams' in test_url:
        return 'movie'
    if '/series/' in test_url or 'action=get_series' in test_url:
        return 'series'

    # Generic regex for after the domain or anywhere in path
    if re.search(r'/(movie|movies)/', test_url):
        return 'movie'
    if re.search(r'/(series|tvshows|episodes)/', test_url):
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
    """Parse series name, season, and episode from title with multiple patterns"""
    # Clean common prefixes to improve grouping
    # Matches: "US:", "AMZ -", "4K-AMZ -", "NF -", "GR -", etc.
    # We strip these so "AMZ - Show" and "4K-AMZ - Show" group together
    # and "US: Show" and "UK: Show" group together (which is usually desired for unified listing)
    prefixes = r'^(?:(?:US|UK|CA|AMZ|NF|HULU|DSNY|GR|EN|DE|IT|FR|ES|PT|PL|TR|4K|FHD|HD|SD|RAW|HEVC|VOD|VIP)\s*[-:|]\s*)+'
    clean_title = re.sub(prefixes, '', title, flags=re.IGNORECASE).strip()

    # 0. Season-only "Up to" pattern: "(Up to S02 Complete)" / "(Up to Season 2 Complete)"
    match = re.search(r'(.*?)\s*\(Up to\s+(?:S|Season)\s*(\d+)\s*(?:Complete|Full)\)', clean_title, re.IGNORECASE)
    if match:
        series_name = match.group(1).strip(" -:")
        season = int(match.group(2))
        if season <= 1900:
            return {
                'series_name': series_name,
                'season': season,
                'episode': 0,  # 0 = complete season, no specific episode
                'is_series': True
            }

    # 1. Standard "S01 E01" / "S01E01" / "Season 01 Episode 01"
    # Matches: "Show S01E01", "Show Season 1 Episode 1", "Show S01 E01"
    # Also handles: "Show (Up to S01E01)" patterns
    # Try the "Up to" pattern first
    match = re.search(r'(.*?)\s*\(Up to\s+(?:S|Season)\s*(\d+)\s*(?:E|Ep|Episode|x)\s*(\d+)\)', clean_title, re.IGNORECASE)
    if match:
        series_name = match.group(1).strip(" -:")
        season = int(match.group(2))
        episode = int(match.group(3))
        # Check if the captured number is a year (e.g. 2024), if so, ignore
        if season > 1900 or episode > 1900:
            pass  # Continue to next pattern
        else:
            return {
                'series_name': series_name,
                'season': season,
                'episode': episode,
                'is_series': True
            }

    # Try standard pattern without "Up to"
    match = re.search(r'(.*?)(?:S|Season)\s*(\d+)\s*(?:E|Ep|Episode|x)\s*(\d+)', clean_title, re.IGNORECASE)
    if match:
        series_name = match.group(1).strip(" -:")
        season = int(match.group(2))
        episode = int(match.group(3))
        # Check if the captured number is a year (e.g. 2024), if so, ignore
        if season > 1900 or episode > 1900:
            pass  # Continue to next pattern
        else:
            return {
                'series_name': series_name,
                'season': season,
                'episode': episode,
                'is_series': True
            }

    # 2. "1x01" format
    # Try the "Up to" pattern first
    match = re.search(r'(.*?)\s*\(Up to\s+(\d+)x(\d+)\)', clean_title, re.IGNORECASE)
    if match:
        series_name = match.group(1).strip(" -:")
        season = int(match.group(2))
        episode = int(match.group(3))
        if season > 1900 or episode > 1900:
            pass  # Continue to next pattern
        else:
            return {
                'series_name': series_name,
                'season': season,
                'episode': episode,
                'is_series': True
            }

    # Try standard "1x01" pattern
    match = re.search(r'(.*?)(\d+)x(\d+)', clean_title, re.IGNORECASE)
    if match:
        series_name = match.group(1).strip(" -:")
        season = int(match.group(2))
        episode = int(match.group(3))
        if season > 1900 or episode > 1900:
            pass  # Continue to next pattern
        else:
            return {
                'series_name': series_name,
                'season': season,
                'episode': episode,
                'is_series': True
            }

    # 3. "Episode 01" / "Ep 01" / "E01" / "Series 1" / "Part 1" format
    # Matches: "Title Episode 1", "Title Ep 1", "Title E1", "Title - E1", "Title Part 1", "Title Vol 1", "Title Series 1"
    # Try the "Up to" pattern first
    match = re.search(r'(.*?)\s*\(Up to\s+(?:Episode|Ep|E|Part|Pt|Vol|Volume|Series)\s*(\d+)\)', clean_title, re.IGNORECASE)
    if match:
        potential_series_name = match.group(1).strip(" -:")
        episode_num = int(match.group(2))

        # Check if the captured number is a year (e.g. 2024), if so, ignore
        if episode_num > 1900:
            pass  # Not a series
        else:
            # For this pattern, we assume Season 1 if not specified
            return {
                'series_name': potential_series_name,
                'season': 1,
                'episode': episode_num,
                'is_series': True
            }

    # Try standard pattern
    match = re.search(r'(.*?)(?:Episode|Ep|E|Part|Pt|Vol|Volume|Series)\s*(\d+)', clean_title, re.IGNORECASE)
    if match:
        potential_series_name = match.group(1).strip(" -:")
        episode_num = int(match.group(2))

        # Check if the captured number is a year (e.g. 2024), if so, ignore
        if episode_num > 1900:
            pass  # Not a series
        else:
            # For this pattern, we assume Season 1 if not specified
            return {
                'series_name': potential_series_name,
                'season': 1,
                'episode': episode_num,
                'is_series': True
            }

    # 4. Fallback: Check for common series indicators anywhere in the title
    # Look for patterns like "S01", "Season 1", "Series 1", etc.
    # Also handles "(Up to S01)" patterns
    if re.search(r'(?:\b|Up to\s+)(?:S\d+|Season \d+|Series \d+)\b', clean_title, re.IGNORECASE):
        # If we find series indicators but couldn't parse them, treat as series with default values
        return {
            'series_name': clean_title,
            'season': 1,
            'episode': 1,
            'is_series': True
        }

    return {
        'series_name': clean_title or title,
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
        
        # Determine series info - use parsed if valid, else fallback
        if parsed['is_series']:
            s_name = parsed['series_name']
            season_num = str(parsed['season'])
            ep_num = parsed['episode']
        else:
            # Fallback for items that are in a Series group but don't look like "S01E01"
            # Strip common prefixes so "GR - Show" and "EN - Show" group together properly
            prefixes_re = r'^(?:(?:US|UK|CA|AMZ|NF|HULU|DSNY|GR|EN|DE|IT|FR|ES|PT|PL|TR|4K|FHD|HD|SD|RAW|HEVC|VOD|VIP)\s*[-:|]\s*)+'
            s_name = re.sub(prefixes_re, '', channel['name'], flags=re.IGNORECASE).strip() or channel['name']
            season_num = "1"
            ep_num = 1
            
        if s_name not in series_data:
            series_data[s_name] = {'seasons': {}}
        
        if season_num not in series_data[s_name]['seasons']:
            series_data[s_name]['seasons'][season_num] = []
        
        # Check if this episode already exists to avoid duplicates (or maybe we want duplicates if different URLs?)
        # For now, append all.
        series_data[s_name]['seasons'][season_num].append({
            'episode': ep_num,
            'name': channel['name'],
            'url': channel.get('url', '')
        })
    
    # CSS for the three-column layout
    css = """
        .series-container {
            display: grid;
            grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) minmax(280px, 2fr);
            gap: 1rem;
            background: transparent;
            height: calc(100vh - 280px);
            min-height: 480px;
        }
        .column {
            background: #1c1b1b;
            border: 1px solid rgba(255,255,255,0.04);
            border-radius: 0.75rem;
            overflow-y: auto;
            height: 100%;
        }
        .column::-webkit-scrollbar { width: 4px; }
        .column::-webkit-scrollbar-track { background: transparent; }
        .column::-webkit-scrollbar-thumb { background: #353534; border-radius: 9999px; }
        .column-header {
            position: sticky;
            top: 0;
            background: #201f1f;
            color: #a8e8ff;
            padding: 0.75rem 1rem;
            font-weight: 800;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .list-item {
            padding: 0.6rem 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.03);
            cursor: pointer;
            font-size: 0.825rem;
            color: #bbc9cf;
            transition: background 0.15s;
        }
        .list-item:hover { background: rgba(255,255,255,0.03); color: #e5e2e1; }
        .list-item.active { background: rgba(0,212,255,0.1); color: #00d4ff; }
        .episode-table { width: 100%; border-collapse: collapse; }
        .episode-table th,
        .episode-table td {
            padding: 0.5rem 0.75rem;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            text-align: left;
            vertical-align: middle;
            font-size: 0.8rem;
        }
        .episode-table th {
            font-size: 0.65rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: rgba(255,255,255,0.3);
            background: #131313;
        }
        .stream-actions { display: flex; flex-direction: column; gap: 4px; }
        .stream-actions .action-btn { margin: 2px 0; }
        .series-info { padding: 0.75rem 1rem; font-size: 0.8rem; color: #bbc9cf; }
        .total-episodes {
            font-size: 0.65rem;
            background: rgba(0,212,255,0.1);
            color: #00d4ff;
            padding: 0.1rem 0.4rem;
            border-radius: 9999px;
            margin-left: 0.4rem;
            font-weight: 600;
        }
        @media (max-width: 768px) {
            .stream-actions { flex-direction: column; }
            .action-btn { margin: 4px 0; text-align: center; }
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
                <span class="total-episodes">{total_episodes} Season(s)</span>
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
                                    <td>${{ep.episode === 0 ? 'Complete' : 'E' + ep.episode.toString().padStart(2, '0')}}</td>
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
        safe_group_id = 'g-' + ''.join(c if c.isalnum() or c == '-' else '-' for c in group_name.lower())[:60]
        return f"""
            <div class="group" id="{safe_group_id}">
                <div class="group-header">
                    <span class="chevron">&#9660;</span>
                    <span class="group-name">{group_name}</span>
                    <span class="group-count" data-total="{len(channels)}">{len(channels)}</span>
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
            logo_html = f'<img src="{channel["logo"]}" loading="lazy" alt="{"Movie Poster" if is_movie else "Channel Logo"}" class="{logo_class}" onerror="this.style.display=\'none\'">'
            
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
        safe_name = channel['name'].lower().replace('"', '').replace("'", '')
        channel_rows.append(f"""
            <tr data-name="{safe_name}">
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
    
    safe_group_id = 'g-' + ''.join(c if c.isalnum() or c == '-' else '-' for c in group_name.lower())[:60]
    return f"""
        <div class="group" id="{safe_group_id}">
            <div class="group-header">
                <span class="chevron">&#9660;</span>
                <span class="group-name">{group_name}</span>
                <span class="group-count" data-total="{len(channels)}">{len(channels)}</span>
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
            grid-template-columns: 220px 220px 1fr;
            gap: 1rem;
            background: transparent;
        }
        .column {
            background: #1c1b1b;
            border: 1px solid rgba(255,255,255,0.04);
            border-radius: 0.75rem;
            height: 580px;
            overflow-y: auto;
        }
        .column::-webkit-scrollbar { width: 4px; }
        .column::-webkit-scrollbar-track { background: transparent; }
        .column::-webkit-scrollbar-thumb { background: #353534; border-radius: 9999px; }
        .column-header {
            padding: 0.75rem 1rem;
            background: #201f1f;
            color: #a8e8ff;
            position: sticky;
            top: 0;
            font-size: 0.72rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .item-list { list-style: none; margin: 0; padding: 0; }
        .list-item {
            padding: 0.55rem 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.03);
            cursor: pointer;
            font-size: 0.8rem;
            color: #bbc9cf;
            transition: background 0.15s;
        }
        .list-item:hover { background: rgba(255,255,255,0.03); color: #e5e2e1; }
        .list-item.active { background: rgba(0,212,255,0.1); color: #00d4ff; font-weight: 600; }
        .episode-table { width: 100%; border-collapse: collapse; }
        .episode-table th, .episode-table td {
            padding: 0.5rem 0.75rem;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            font-size: 0.8rem;
        }
        .episode-table th {
            font-size: 0.65rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: rgba(255,255,255,0.3);
            background: #131313;
        }
        .content-type-selector { margin-bottom: 1rem; }
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
            # The series_name should already be clean from organize_series_content
            # Just use it as-is, but clean any remaining artifacts
            base_name = series_name.strip()
            
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
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem;">
                <h1>Content Analysis</h1>
                <a href="/" class="back-btn">&#8592; Playlists</a>
            </div>
            <div class="timestamp">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
            <div style="display:flex; flex-wrap:wrap; gap:1.5rem; margin-top:0.75rem;">
                <div><span style="font-family:Manrope,sans-serif;font-weight:800;font-size:1.2rem;color:#00d4ff;">{total_channels}</span><span style="display:block;font-size:0.65rem;text-transform:uppercase;letter-spacing:0.07em;color:rgba(255,255,255,0.35);">With TVG-ID</span></div>
                <div><span style="font-family:Manrope,sans-serif;font-weight:800;font-size:1.2rem;color:#a8e8ff;">{total_epg_matches}</span><span style="display:block;font-size:0.65rem;text-transform:uppercase;letter-spacing:0.07em;color:rgba(255,255,255,0.35);">EPG Matches</span></div>
                <div><span style="font-family:Manrope,sans-serif;font-weight:800;font-size:1.2rem;color:rgba(255,255,255,0.6);">{total_movies}</span><span style="display:block;font-size:0.65rem;text-transform:uppercase;letter-spacing:0.07em;color:rgba(255,255,255,0.35);">Movies</span></div>
                <div><span style="font-family:Manrope,sans-serif;font-weight:800;font-size:1.2rem;color:rgba(255,255,255,0.6);">{total_series}</span><span style="display:block;font-size:0.65rem;text-transform:uppercase;letter-spacing:0.07em;color:rgba(255,255,255,0.35);">Series</span></div>
                <div><span style="font-family:Manrope,sans-serif;font-weight:800;font-size:1.2rem;color:rgba(255,255,255,0.6);">{total_unmatched}</span><span style="display:block;font-size:0.65rem;text-transform:uppercase;letter-spacing:0.07em;color:rgba(255,255,255,0.35);">Other</span></div>
            </div>
        </div>

        <div class="nav-tabs">
            <a href="content_analysis_matched.html" class="tab">EPG ({total_epg_matches})</a>
            <a href="content_analysis_unmatched.html" class="tab">No EPG ({total_channels - total_epg_matches})</a>
            <a href="content_analysis_movies.html" class="tab">Movies ({total_movies})</a>
            <a href="content_analysis_series.html" class="tab">Series ({total_series})</a>
            <a href="content_analysis_unmatched_no_tvg.html" class="tab">Other ({total_unmatched})</a>
        </div>
        <div class="search-filter-bar">
            <div class="search-pill">
                <i class="fa fa-search s-icon"></i>
                <input type="text" id="contentSearch" placeholder="Search content\u2026" oninput="filterContent(this.value)" autocomplete="off">
                <button class="search-clear" id="clearBtn" onclick="clearSearch()" title="Clear">\u00d7</button>
            </div>
            <select class="group-jump" id="groupJump" onchange="jumpToGroup(this.value)">
                <option value="">Jump to group\u2026</option>
            </select>
            <span class="result-count" id="resultCount"></span>
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
                    button.style.fontWeight = 'bold';
                    button.style.padding = '6px 10px';
                } else {
                    button.style.display = 'none';
                }
            });

            // Collapse all groups on load
            document.querySelectorAll('.group').forEach(g => g.classList.add('collapsed'));

            // Group header click to toggle collapse
            document.querySelectorAll('.group-header').forEach(h => {
                h.addEventListener('click', function(e) {
                    if (e.target.closest('a,button')) return;
                    this.closest('.group').classList.toggle('collapsed');
                });
            });

            // Build group jump dropdown from DOM
            const sel = document.getElementById('groupJump');
            if (sel) {
                document.querySelectorAll('.group[id]').forEach(g => {
                    const nameEl = g.querySelector('.group-name');
                    if (nameEl) {
                        const opt = document.createElement('option');
                        opt.value = g.id;
                        opt.textContent = nameEl.textContent.trim();
                        sel.appendChild(opt);
                    }
                });
            }
        });

        // Real-time search filter (debounced)
        let _filterTimer;
        function filterContent(query) {
            clearTimeout(_filterTimer);
            _filterTimer = setTimeout(function() {
                const q = query.toLowerCase().trim();
                const clearBtn = document.getElementById('clearBtn');
                if (clearBtn) clearBtn.style.display = q ? 'flex' : 'none';
                let totalVisible = 0;

                document.querySelectorAll('.group').forEach(function(group) {
                    const rows = group.querySelectorAll('tr[data-name]');
                    let groupVisible = 0;

                    if (rows.length > 0) {
                        rows.forEach(function(row) {
                            const match = !q || row.dataset.name.includes(q);
                            row.style.display = match ? '' : 'none';
                            if (match) groupVisible++;
                        });
                    } else {
                        // Series/other: match against group name
                        const nameEl = group.querySelector('.group-name');
                        groupVisible = (!q || (nameEl && nameEl.textContent.toLowerCase().includes(q))) ? 1 : 0;
                    }

                    totalVisible += groupVisible;
                    group.style.display = (groupVisible === 0 && q) ? 'none' : '';
                    if (q) group.classList.remove('collapsed');
                    else if (!q) group.classList.add('collapsed');

                    const badge = group.querySelector('.group-count');
                    if (badge) {
                        badge.textContent = (q && rows.length > 0) ? groupVisible : badge.dataset.total;
                    }
                });

                const rc = document.getElementById('resultCount');
                if (rc) rc.textContent = q ? (totalVisible.toLocaleString() + ' results') : '';
            }, 150);
        }

        function clearSearch() {
            const inp = document.getElementById('contentSearch');
            if (inp) inp.value = '';
            filterContent('');
        }

        function jumpToGroup(groupId) {
            if (!groupId) return;
            const el = document.getElementById(groupId);
            if (!el) return;
            el.classList.remove('collapsed');
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
            const sel = document.getElementById('groupJump');
            if (sel) sel.value = '';
        }
    """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Content Analysis</title>
        <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;700;800&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <style>
            {css_styles}
            .nav-tabs {{ display: flex; gap: 0.4rem; margin-bottom: 1.5rem; flex-wrap: wrap; }}
            .tab {{
                padding: 0.35rem 0.85rem;
                background: #353534;
                color: rgba(255,255,255,0.55);
                border-radius: 9999px;
                text-decoration: none;
                font-family: 'Inter', sans-serif;
                font-size: 0.7rem;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                transition: all 0.15s;
            }}
            .tab:hover {{ background: #2a2a2a; color: white; }}
            .tab.active {{ background: #00d4ff; color: #003642; font-weight: 700; }}
            .vlc-btn {{
                background: rgba(245,130,32,0.2);
                color: #ffba3d;
                padding: 0.28rem 0.65rem;
                border-radius: 9999px;
                text-decoration: none;
                display: inline-block;
                font-family: 'Inter', sans-serif;
                font-size: 0.68rem;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                transition: all 0.15s;
            }}
            .vlc-btn:hover {{ background: rgba(245,130,32,0.35); color: #ffba3d; text-decoration: none; }}
            .vlc-ios-btn {{
                background: rgba(0,122,255,0.2);
                color: #a8e8ff;
                padding: 0.28rem 0.65rem;
                border-radius: 9999px;
                text-decoration: none;
                display: inline-block;
                font-family: 'Inter', sans-serif;
                font-size: 0.68rem;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                transition: all 0.15s;
            }}
            .vlc-ios-btn:hover {{ background: rgba(0,122,255,0.35); text-decoration: none; }}
            .vlc-android-btn {{
                background: rgba(61,220,132,0.2);
                color: #3cd7ff;
                padding: 0.28rem 0.65rem;
                border-radius: 9999px;
                text-decoration: none;
                display: inline-block;
                font-family: 'Inter', sans-serif;
                font-size: 0.68rem;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                transition: all 0.15s;
            }}
            .vlc-android-btn:hover {{ background: rgba(61,220,132,0.35); text-decoration: none; }}
            .copy-btn {{
                background: rgba(0,212,255,0.12);
                color: #a8e8ff;
                padding: 0.28rem 0.65rem;
                border-radius: 9999px;
                border: none;
                display: inline-block;
                font-family: 'Inter', sans-serif;
                font-size: 0.68rem;
                font-weight: 500;
                cursor: pointer;
                text-transform: uppercase;
                letter-spacing: 0.04em;
                transition: all 0.15s;
            }}
            .copy-btn:hover {{ background: #00d4ff; color: #003642; }}
            .stream-cell {{ white-space: nowrap; }}
            .stream-actions {{ display: flex; flex-direction: column; gap: 4px; }}
            .platform-info {{
                background: rgba(0,212,255,0.05);
                border-left: 3px solid #00d4ff;
                padding: 0.65rem 1rem;
                margin: 0.75rem 0 1.25rem;
                border-radius: 0 0.5rem 0.5rem 0;
                font-size: 0.78rem;
                color: #bbc9cf;
            }}
            @media (max-width: 768px) {{
                .stream-actions {{ flex-direction: column; }}
                .action-btn {{ margin: 4px 0; text-align: center; }}
                .container {{ padding: 0.75rem; }}
                table {{ display: block; overflow-x: auto; }}
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
            font-family: 'Inter', sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 0;
            background: #131313;
            color: #e5e2e1;
        }
        .container {
            width: 100%;
            padding: 1.25rem 1.5rem;
        }
        .header {
            background: #1c1b1b;
            padding: 1.25rem 1.5rem;
            margin-bottom: 1.25rem;
            border-radius: 0.75rem;
        }
        .header h1 {
            font-family: 'Manrope', sans-serif;
            font-weight: 800;
            font-size: 1.4rem;
            letter-spacing: -0.03em;
            color: #e5e2e1;
            margin: 0;
        }
        .header p { color: #bbc9cf; font-size: 0.85rem; margin: 0.2rem 0; }
        .header .timestamp { font-size: 0.7rem; color: rgba(255,255,255,0.3); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 0.5rem; display: block; }
        .group {
            background: #1c1b1b;
            padding: 1.25rem 1.5rem;
            margin-bottom: 0.5rem;
            border-radius: 0.625rem;
            content-visibility: auto;
            contain-intrinsic-size: 0 500px;
        }
        .group-header {
            background: transparent;
            color: #a8e8ff;
            font-family: 'Manrope', sans-serif;
            font-weight: 800;
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            padding: 0 0 0.6rem 0;
            margin: 0 0 0.75rem 0;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            cursor: pointer;
            user-select: none;
        }
        .group-header:hover { color: #00d4ff; }
        .chevron { font-size: 0.7rem; transition: transform 0.2s; flex-shrink: 0; }
        .group.collapsed .chevron { transform: rotate(-90deg); }
        .group-name { flex: 1; }
        .group-count {
            background: #353534;
            color: rgba(255,255,255,0.5);
            padding: 0.1rem 0.5rem;
            border-radius: 9999px;
            font-size: 0.68rem;
            font-weight: 600;
            font-family: 'Inter', sans-serif;
        }
        .group.collapsed > *:not(.group-header) { display: none !important; }
        .search-filter-bar {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.75rem 0;
            margin-bottom: 1rem;
            flex-wrap: wrap;
            position: sticky;
            top: 0;
            z-index: 100;
            background: #131313;
        }
        .search-pill {
            position: relative;
            flex: 1;
            min-width: 200px;
            max-width: 480px;
        }
        .search-pill .s-icon {
            position: absolute;
            left: 1rem;
            top: 50%;
            transform: translateY(-50%);
            font-size: 14px;
            color: #00d4ff;
            pointer-events: none;
        }
        .search-pill input {
            width: 100%;
            background: #0e0e0e;
            border: none;
            border-radius: 9999px;
            padding: 0.6rem 2.5rem 0.6rem 2.75rem;
            color: #e5e2e1;
            font-family: 'Inter', sans-serif;
            font-size: 0.875rem;
            outline: none;
            transition: box-shadow 0.2s;
        }
        .search-pill input:focus { box-shadow: 0 0 0 2px #00d4ff; }
        .search-pill input::placeholder { color: rgba(255,255,255,0.3); }
        .search-clear {
            position: absolute;
            right: 0.75rem;
            top: 50%;
            transform: translateY(-50%);
            background: #353534;
            border: none;
            border-radius: 9999px;
            color: rgba(255,255,255,0.6);
            width: 20px;
            height: 20px;
            cursor: pointer;
            font-size: 11px;
            display: none;
            align-items: center;
            justify-content: center;
            line-height: 1;
        }
        .result-count {
            font-size: 0.7rem;
            color: rgba(255,255,255,0.4);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            white-space: nowrap;
        }
        .group-jump {
            background: #1c1b1b;
            border: none;
            border-radius: 9999px;
            color: #e5e2e1;
            font-family: 'Inter', sans-serif;
            font-size: 0.75rem;
            padding: 0.55rem 1.1rem;
            cursor: pointer;
            outline: none;
            transition: box-shadow 0.2s;
            max-width: 240px;
        }
        .group-jump:focus { box-shadow: 0 0 0 2px #00d4ff; }
        .epg-match { color: #00d4ff; }
        .epg-no-match { color: #ff6b6b; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 0.75rem;
        }
        th {
            padding: 0.55rem 0.75rem;
            text-align: left;
            font-size: 0.65rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: rgba(255,255,255,0.3);
            border-bottom: 1px solid rgba(255,255,255,0.06);
            background: #131313;
        }
        td {
            padding: 0.55rem 0.75rem;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            font-size: 0.82rem;
            color: #e5e2e1;
            vertical-align: middle;
        }
        tr:hover td { background: rgba(255,255,255,0.015); }
        .command {
            background: #0e0e0e;
            padding: 0.875rem 1rem;
            border-radius: 0.5rem;
            overflow-x: auto;
            white-space: pre-wrap;
            font-family: monospace;
            font-size: 0.72rem;
            color: #a8e8ff;
            border: 1px solid rgba(0,212,255,0.1);
        }
        .section-header {
            background: transparent;
            color: #a8e8ff;
            font-family: 'Manrope', sans-serif;
            font-weight: 800;
            font-size: 0.95rem;
            letter-spacing: -0.01em;
            padding: 0.4rem 0;
            margin: 1.25rem 0 0.75rem;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .section-header h2 { margin: 0; font-size: inherit; font-weight: inherit; color: inherit; }
        .series-group { margin-bottom: 0.375rem; }
        .series-header {
            background: #201f1f;
            color: #e5e2e1;
            padding: 0.7rem 1rem;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-radius: 0.5rem;
            font-family: 'Manrope', sans-serif;
            font-weight: 700;
            font-size: 0.85rem;
            transition: background 0.15s;
            border: 1px solid rgba(255,255,255,0.04);
        }
        .series-header:hover { background: #2a2a2a; }
        .series-content {
            display: none;
            padding: 0.875rem;
            background: #1c1b1b;
            border: 1px solid rgba(255,255,255,0.04);
            border-top: none;
            border-radius: 0 0 0.5rem 0.5rem;
        }
        .season-content {
            margin: 0.375rem 0;
            padding: 0.625rem 0.875rem;
            background: #201f1f;
            border-radius: 0.375rem;
        }
        .episode-count {
            font-size: 0.68rem;
            background: rgba(0,212,255,0.1);
            color: #00d4ff;
            padding: 0.1rem 0.45rem;
            border-radius: 9999px;
        }
        .back-btn {
            background: #353534;
            color: rgba(255,255,255,0.65);
            padding: 0.4rem 0.9rem;
            border: none;
            border-radius: 9999px;
            text-decoration: none;
            font-family: 'Inter', sans-serif;
            font-size: 0.7rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            transition: all 0.15s;
            display: inline-block;
        }
        .back-btn:hover { background: #2a2a2a; color: white; text-decoration: none; }
        .movie-poster {
            width: 56px !important;
            height: 84px !important;
            object-fit: cover !important;
            border-radius: 0.375rem;
            vertical-align: middle;
            transition: transform 0.3s ease;
        }
        .movie-poster:hover {
            transform: scale(3);
            transform-origin: center left;
            position: relative;
            z-index: 1000;
            box-shadow: 0 8px 24px rgba(0,0,0,0.7);
        }
        .poster-cell {
            width: 66px !important;
            min-width: 66px !important;
            max-width: 66px !important;
            padding: 3px !important;
            position: relative;
        }
        .movie-table { table-layout: fixed !important; width: 100%; }
        .movie-table img { max-width: 56px !important; max-height: 84px !important; }
        .movie-table td { vertical-align: middle; padding: 0.45rem 0.75rem; }
        .actions-cell { white-space: nowrap; width: 150px; }
        .action-btn {
            display: inline-block;
            padding: 0.28rem 0.65rem;
            margin: 0 2px;
            border-radius: 9999px;
            text-decoration: none;
            color: rgba(255,255,255,0.7);
            font-family: 'Inter', sans-serif;
            font-size: 0.68rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            transition: all 0.15s;
        }
        .action-btn:hover { text-decoration: none; }
        .download-btn { background: rgba(0,212,255,0.15); color: #a8e8ff; }
        .download-btn:hover { background: #00d4ff; color: #003642; }
        .watch-btn { background: rgba(60,215,255,0.15); color: #3cd7ff; }
        .watch-btn:hover { background: #00d4ff; color: #003642; }
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
    
    # Update shared header to include new statistics (reuse styled header with search)
    shared_header = generate_shared_header(
        total_channels=total_channels,
        total_epg_matches=total_epg_matches,
        total_movies=total_movies,
        total_series=total_series,
        total_unmatched=total_unmatched,
        m3u_editor_command=m3u_editor_command
    )
    
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
            css_styles
        ))
    print(f"- {series_file}")
        
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