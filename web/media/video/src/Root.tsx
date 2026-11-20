import React from 'react';
import {Composition} from 'remotion';
import {TOTAL, Workflow} from './Workflow';
import {Opening, OPENING_FRAMES} from './opening/Opening';
import {Opening3D, OPENING3D_FRAMES} from './opening/Opening3D';
import {Demo as DemoComp, DEMO_FRAMES} from './demo/Demo';
import {ValidateWeb} from './web/ValidateWeb';
import {TOTAL_WEB, WorkflowWeb} from './WorkflowWeb';

export const RemotionRoot: React.FC = () => (
	<>
		<Composition id="Workflow" component={Workflow} durationInFrames={TOTAL} fps={30} width={1920} height={1080} />
		<Composition id="WorkflowWeb" component={WorkflowWeb} durationInFrames={TOTAL_WEB} fps={30} width={1920} height={1080} />
		<Composition id="WebSample" component={ValidateWeb} durationInFrames={240} fps={30} width={1920} height={1080} />
		<Composition id="Opening" component={Opening} durationInFrames={OPENING_FRAMES} fps={30} width={1920} height={1080} />
		<Composition id="Opening3D" component={Opening3D} durationInFrames={OPENING3D_FRAMES} fps={30} width={1920} height={1080} />
		<Composition id="Demo" component={DemoComp} durationInFrames={DEMO_FRAMES} fps={30} width={1920} height={1080} />
	</>
);
