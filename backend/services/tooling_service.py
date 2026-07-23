from __future__ import annotations

from domain.models import DiagnosticsResponse, ToolReadiness
from adapters.process_utils import find_command_path


class ToolingService:
    TOOL_NAMES = ['ffmpeg', 'yt-dlp', 'demucs']

    def diagnostics(self) -> DiagnosticsResponse:
        tools: list[ToolReadiness] = []
        for name in self.TOOL_NAMES:
            path = find_command_path(name)
            tools.append(
                ToolReadiness(
                    name=name,
                    available=bool(path),
                    path=path,
                    detail=None if path else f'{name} is not installed or not on PATH',
                )
            )
        return DiagnosticsResponse(ready=all(tool.available for tool in tools), tools=tools)


tooling_service = ToolingService()
