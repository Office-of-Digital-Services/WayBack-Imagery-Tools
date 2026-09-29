# ArcGIS Pro Tools for Esri WayBack Imagery
[Esri's Wayback imagery](https://www.esri.com/arcgis-blog/products/arcgis-living-atlas/mapping/use-world-imagery-wayback) is an archive of all of the imagery that has appeared in their "Esri World Imagery" basemap since 2014.

Esri provides a useful viewer for this data at https://livingatlas.arcgis.com/wayback/, but what about use in desktop tools
or code?

## Structural Caveats
Wayback is great, but it's important to know that the *prominently displayed dates are not the date of the image capture*!
They are the date the basemap version was released. Imagery in a given location mostly stays the same between releases -
Esri updates some places and not others, and a location may go 6 months or 5 years between new imagery.

The behavior is also scale-dependent! Sources vary depending on zoom, which you can see when images change as you zoom in and out.
That means the dates of the images also change and you need to know the scale or zoom *and* the release date information
to *then* be able to query for the actual date of the image. The World Imagery Wayback tool in the browser does this for you
when you click on an image, but this project aims to make some form of that behavior available directly in ArcGIS, along
with notes for accessing imagery for users of other tools, including QGIS and/or custom software and code.

## The WMTS Server
If all you need is just the imagery, and you don't care about the exact date of the images within the scene, you can use
the WMTS service, which includes a layer for each date of the imagery release.

The WMTS service does *not* provide a GetFeatureInfo endpoint and ArcGIS does not support GetFeatureInfo calls for WMTS layers,
so adding it to a map means it is *only* for visualization and knowing the imagery is not any newer than the release date, but
could be any amount of time *older*.

WMTS URL: https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/WMTS/1.0.0/WMTSCapabilities.xml

ArcGIS Users may see also: https://www.esri.com/arcgis-blog/products/arcgis-living-atlas/imagery/wayback-server-connection-in-pro

## License
[MIT License](LICENSE)

## GenAI Disclosure and Contributions
This project has been developed with generative AI (large language models/LLMs) using a desktop-based agent backed by CDT's Poppy GenAI environment. It
has used a mix of models, starting with Anthropic Claude before moving to Gemini 3.7 Flash as a cheaper and effective model.
While generative AI was used to make the proof of concept and the majority of refinements, standard software engineering and coding
have also been part of the development.

Anyone wishing to submit pull requests coded either on their own, with GenAI, or with a mix, may do so, but the generative AI
use must be disclosed in the pull request along with some approximation of how much of the code was GenAI (fully, mostly, partially, none).
Ultimately, the software engineer submitting the code is the person responsible for the code's quality and correctness.
Low quality submissions reflect on the person in addition to the model and it is not sufficient to deflect responsibility
to the tool. That means you must understand what is in the code you are contributing, and if you do not have the software
engineering experience to evaluate its quality - but you believe it to be working, performant, and correct - state that you need help reviewing the quality in your pull request so
we know what to expect.

Finally, a system prompt for AI agents is located in [.junie/AGENTS.md](.junie/AGENTS.md) - if you code with an AI agent,
please review the instructions in that prompt and determine which parts make sense to provide to your own agent.