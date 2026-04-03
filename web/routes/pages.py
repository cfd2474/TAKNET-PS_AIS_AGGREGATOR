"""Misc page routes."""
import os

from flask import Blueprint, render_template, abort
from flask_login import current_user
from routes.auth_utils import login_required_any, network_admin_required, admin_required
from models import OutputModel

bp = Blueprint("pages", __name__)


def _map_site_coords():
    try:
        lat = float(os.environ.get("SITE_LAT", "33.8753"))
        lon = float(os.environ.get("SITE_LON", "-117.5664"))
        return lat, lon
    except (TypeError, ValueError):
        return 33.8753, -117.5664


@bp.route("/map")
@login_required_any
def map_page():
    lat, lon = _map_site_coords()
    return render_template("map.html", site_lat=lat, site_lon=lon)


@bp.route("/stats")
@network_admin_required
def stats():
    return render_template("stats.html")

@bp.route("/outputs")
@network_admin_required
def outputs():
    return render_template("outputs.html")

@bp.route("/outputs/<int:output_id>/cotproxy")
@network_admin_required
def output_cotproxy(output_id):
    """COTProxy-style transform config page for a CoT output (manual entries + CSV import)."""
    import json
    from ps_air_icons import get_ps_air_icons_list
    output = OutputModel.get_by_id(output_id, int(current_user.id), current_user.role)
    if not output:
        abort(404)
    if output.get("output_type") != "cot":
        abort(404)
    output_config = json.loads(output.get("config") or "{}")
    ps_air_icons = get_ps_air_icons_list()
    return render_template(
        "output_cotproxy.html",
        output=output,
        output_config=output_config,
        ps_air_icons=ps_air_icons,
    )

@bp.route("/about")
@login_required_any
def about():
    return render_template("about.html")
